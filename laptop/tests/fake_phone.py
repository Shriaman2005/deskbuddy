"""A fake phone for the link tests (test-only: needs asyncssh, which only lives in a test venv or the CI job).

An ssh server on a loopback address with a fixed host key that accepts one client key, like Termux's sshd after
pairing. It allows `ssh -R` onto its own loopback only (as GatewayPorts no does) and acts out the commands Chip sends:
  deploy.DEPLOY_CMD   unpacks the tar from stdin into <home>/deskbuddy (safely: tarfile's "data" filter)
  deploy.HASH_CMD     prints <home>/deskbuddy/.chip-hash
  doctor.py's script  answers that sshd, the supervisor and the server run (tunnel=1 while a -R is up)
anything else exits 127. Nothing is run for real.

    phone = FakePhone(host_key_file, client_pub_file, host="127.0.0.2", port=0, home=tmpdir).start()
    phone.port, phone.deploys, phone.forwards, phone.commands; phone.stop()
Alone: python -I laptop/tests/fake_phone.py HOST_KEY CLIENT_PUB [PORT [HOST]]  (Ctrl+C stops)"""
import asyncio
import io
import os
import sys
import tarfile
import tempfile
import threading

import asyncssh

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # laptop/, for deploy.py
import deploy  # noqa: E402


class FakePhone:
    def __init__(self, host_key, client_pub, host="127.0.0.1", port=0, home=None):
        self.host_key, self.client_pub, self.host, self.port = host_key, client_pub, host, port
        self.home = home or tempfile.mkdtemp(prefix="fake-phone-")
        self.deploys = 0
        self.commands = []   # every command run, in order
        self.forwards = []   # ports the client asked to listen on (-R)
        self.listening = set()
        self.loop = None
        self.server = None
        self._ready = threading.Event()
        self._error = None

    @property
    def files(self):
        return os.path.join(self.home, "deskbuddy")

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()
        if not self._ready.wait(15) or self._error:
            raise RuntimeError(f"fake phone didn't start: {self._error}")
        return self

    def stop(self):
        if self.loop and self.server:
            async def close():
                self.server.close()
                await self.server.wait_closed()
            asyncio.run_coroutine_threadsafe(close(), self.loop).result(10)
            self.loop.call_soon_threadsafe(self.loop.stop)

    def _run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.server = self.loop.run_until_complete(asyncssh.create_server(
                lambda: _Server(self), self.host, self.port,
                server_host_keys=[self.host_key], authorized_client_keys=self.client_pub,
                process_factory=self._process, encoding=None, allow_scp=False,
                agent_forwarding=False, x11_forwarding=False, password_auth=False, kbdint_auth=False))
            self.port = self.server.sockets[0].getsockname()[1]
        except Exception as e:  # noqa: BLE001  (reported by start())
            self._error = e
            self._ready.set()
            return
        self._ready.set()
        self.loop.run_forever()

    async def _process(self, process):
        cmd = process.command or ""
        self.commands.append(cmd)
        try:
            if cmd == deploy.DEPLOY_CMD:
                data = await process.stdin.read()
                os.makedirs(self.files, exist_ok=True)
                with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
                    tar.extractall(self.files, filter="data")
                self.deploys += 1
                process.stdout.write(b"services started\n")
                process.exit(0)
            elif cmd == deploy.HASH_CMD:
                try:
                    with open(os.path.join(self.files, deploy.HASH_FILE), "rb") as f:
                        process.stdout.write(f.read())
                except OSError:
                    pass
                process.exit(0)
            elif "pgrep -x sshd" in cmd:  # doctor.py's phone check
                tunnel = "tunnel=1\n" if self.listening else ""
                process.stdout.write(f"sshd=1\nsupervisor=1\nserver=1\n{tunnel}boot=1\n".encode())
                process.exit(0)
            else:
                process.stderr.write(b"fake phone: unknown command\n")
                process.exit(127)
        except Exception as e:  # noqa: BLE001
            process.stderr.write(f"fake phone: {type(e).__name__}: {e}\n".encode())
            process.exit(1)


class _Server(asyncssh.SSHServer):
    def __init__(self, phone):
        self.phone = phone
        self.conn = None
        self.ports = set()  # this connection's -R listeners

    def connection_made(self, conn):
        self.conn = conn

    def server_requested(self, listen_host, listen_port):
        """-R: only onto this phone's loopback, as Termux's sshd with GatewayPorts no."""
        if listen_host not in ("", "localhost", "127.0.0.1") or not listen_port:
            return False
        self.phone.forwards.append(listen_port)

        async def listen():
            listener = await self.conn.forward_local_port("127.0.0.1", listen_port, listen_host, listen_port)
            self.ports.add(listen_port)
            self.phone.listening.add(listen_port)
            return listener
        return listen()

    def connection_lost(self, exc):
        self.phone.listening -= self.ports


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) < 2:
        sys.exit(__doc__)
    p = FakePhone(args[0], args[1], host=args[3] if len(args) > 3 else "127.0.0.1",
                  port=int(args[2]) if len(args) > 2 else 0).start()
    print(f"fake phone on {p.host}:{p.port}, files in {p.files}", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        p.stop()
