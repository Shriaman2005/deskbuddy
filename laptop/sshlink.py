"""How Chip calls ssh, the same on every OS. The phone's host key is pinned exactly as strictly everywhere:
- the key lives in CONFIG_DIR/known_hosts under the alias chip-phone (so the phone's address may change), checked with
  StrictHostKeyChecking=yes, never updated (UpdateHostKeys=no), and no other known_hosts file counts: the global one is
  an always-empty file in CONFIG_DIR (Windows has no /dev/null); ~/.ssh/known_hosts is never read by these calls.
- BatchMode (no prompts), no agent or X11 forwarding, no local commands.
- Chip's own key CONFIG_DIR/id_ed25519, when it exists, is the only identity offered (IdentitiesOnly=yes) and the one
  pairing hands out; otherwise ssh's own identities as before (pairing hands out the first one `ssh -G` lists).
- scan() reads what a phone offers (ssh-keyscan; ssh itself on Windows).
- ssh, ssh-keygen, ssh-keyscan come from PATH or Windows' System32\\OpenSSH (platforms.proc.which).
- Paths in -o values use forward slashes and double quotes (user names with spaces), with % doubled where ssh expands
  %-tokens."""
import os
import re
import socket
import tempfile

from platforms import paths, proc

HOST_ALIAS = "chip-phone"
KNOWN_HOSTS = paths.config("known_hosts")
NO_GLOBAL = paths.config("known_hosts.none")  # always empty: GlobalKnownHostsFile
OWN_KEY = paths.config("id_ed25519")
TOOLS = ("ssh", "ssh-keygen", "ssh-keyscan")
OPENSSH_FIX = ("add Windows' “OpenSSH Client”: Settings → System → Optional features → View features → OpenSSH Client "
               "(or, as administrator: Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0)")
_version = None


def tool(name):
    """Full path of ssh / ssh-keygen / ssh-keyscan, or the bare name (then running it fails like a missing program)."""
    return proc.which(name) or name


def missing():
    """The ssh tools that aren't installed."""
    return [t for t in TOOLS if not proc.which(t)]


def version():
    """(major, minor) of the OpenSSH client, (0, 0) if unknown. `ssh -V` prints e.g. OpenSSH_9.6p1 or
    OpenSSH_for_Windows_8.1p1 on stderr."""
    global _version
    if _version is None:
        try:
            r = proc.complete([tool("ssh"), "-V"], timeout=6)
            m = re.search(r"OpenSSH_(?:for_Windows_)?(\d+)\.(\d+)", r.stderr + r.stdout)
            _version = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
        except (OSError, proc.TimeoutExpired):
            _version = (0, 0)
    return _version


def quote(path, tokens):
    """A path as an ssh -o value: absolute, forward slashes, double-quoted; % doubled when ssh expands %-tokens there."""
    p = os.path.abspath(path).replace("\\", "/").replace('"', '\\"')
    return '"' + (p.replace("%", "%%") if tokens else p) + '"'


def no_global():
    """The empty file used as GlobalKnownHostsFile (emptied again if anything wrote to it)."""
    try:
        if os.path.getsize(NO_GLOBAL) == 0:
            return NO_GLOBAL
    except OSError:
        os.makedirs(os.path.dirname(NO_GLOBAL), exist_ok=True)
    open(NO_GLOBAL, "w").close()
    return NO_GLOBAL


def own_key():
    """CONFIG_DIR/id_ed25519 if Chip has its own key, else None."""
    return OWN_KEY if os.path.isfile(OWN_KEY) else None


def options(port):
    """The pinned-key options every ssh to the phone uses (the tunnel, deploy, doctor); add the rest and the address."""
    kh_tokens = version() >= (8, 4)  # known-hosts paths take %-tokens since OpenSSH 8.4; IdentityFile always did
    opts = ["-p", str(port), "-o", "BatchMode=yes",
            "-o", f"UserKnownHostsFile={quote(KNOWN_HOSTS, kh_tokens)}",
            "-o", f"GlobalKnownHostsFile={quote(no_global(), kh_tokens)}",
            "-o", f"HostKeyAlias={HOST_ALIAS}", "-o", "StrictHostKeyChecking=yes", "-o", "UpdateHostKeys=no",
            "-o", "CheckHostIP=no", "-o", "ForwardAgent=no", "-o", "ForwardX11=no", "-o", "PermitLocalCommand=no"]
    key = own_key()
    if key:
        opts += ["-o", f"IdentityFile={quote(key, True)}", "-o", "IdentitiesOnly=yes"]
    return opts


def command(ip, port, remote, timeout=8):
    """argv for running one command in Termux (no forwards of any kind)."""
    return [tool("ssh"), *options(port), "-o", "ClearAllForwardings=yes", "-o", f"ConnectTimeout={timeout}", ip, remote]


def scan(ip, port, timeout=3):
    """{(key type, key)} the sshd at ip:port offers now; nothing is trusted or pinned by this.
    Linux/macOS: ssh-keyscan. Windows: ssh-keyscan of Windows' OpenSSH 9.5 proposes key exchanges its LibreSSL build
    can't do (sntrup761), so against Termux's OpenSSH 10 it gets no key at all ("choose_kex: unsupported KEX method").
    There ssh itself reads the ed25519 key (the one the phone's pairing code covers) into a throwaway known_hosts
    with accept-new, and authenticates with nothing."""
    if os.name != "nt":
        return {tuple(l.split()[1:3]) for l in
                proc.run(tool("ssh-keyscan"), "-T", str(timeout), "-p", str(port), ip, timeout=timeout * 2 + 2).splitlines()
                if len(l.split()) >= 3 and not l.startswith("#")}
    fd, tmp = tempfile.mkstemp(prefix="chip-scan-", dir=os.path.dirname(no_global()))
    os.close(fd)
    try:
        proc.run(tool("ssh"), "-F", "none", "-p", str(port), "-o", "BatchMode=yes",
                 "-o", "StrictHostKeyChecking=accept-new", "-o", f"UserKnownHostsFile={quote(tmp, version() >= (8, 4))}",
                 "-o", f"GlobalKnownHostsFile={quote(no_global(), version() >= (8, 4))}", "-o", "HashKnownHosts=no",
                 "-o", "UpdateHostKeys=no", "-o", "CheckHostIP=no", "-o", "HostKeyAlgorithms=ssh-ed25519",
                 "-o", f"ConnectTimeout={timeout}", "-o", "PubkeyAuthentication=no", "-o", "PasswordAuthentication=no",
                 "-o", "KbdInteractiveAuthentication=no", "-o", "GSSAPIAuthentication=no",
                 "-o", "HostbasedAuthentication=no", "-o", "ClearAllForwardings=yes", "-o", "ForwardAgent=no",
                 "-o", "PermitLocalCommand=no", ip, "exit", timeout=timeout * 2 + 2)
        with open(tmp, encoding="utf-8", errors="replace") as f:
            return {tuple(l.split()[1:3]) for l in f if len(l.split()) >= 3 and not l.startswith("#")}
    except OSError:
        return set()
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def public_key():
    """The public half of the key the phone will see: Chip's own, or the first identity `ssh -G` lists that exists."""
    if own_key():
        with open(OWN_KEY + ".pub", encoding="utf-8") as f:
            return f.read().strip()
    for line in proc.run(tool("ssh"), "-G", "chip-pairing.invalid").splitlines():
        if line.startswith("identityfile "):
            path = os.path.expanduser(line.split(None, 1)[1]) + ".pub"
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as f:
                    return f.read().strip()
    return None


def pinned():
    """{(key type, key)} pinned for the phone."""
    try:
        with open(KNOWN_HOSTS, encoding="utf-8") as f:
            return {tuple(l.split()[1:3]) for l in f if len(l.split()) >= 3 and not l.startswith("#")}
    except OSError:
        return set()


def ensure_own_key():
    """Makes CONFIG_DIR/id_ed25519 (no passphrase) if there is none and no phone is pinned yet, so a working link that
    uses ~/.ssh's key is never broken. Called by install.py; arguments as a list, never through PowerShell (which drops
    the empty -N ""). Returns the key's path, or None."""
    if own_key():
        return OWN_KEY
    if pinned():
        return None
    os.makedirs(os.path.dirname(OWN_KEY), exist_ok=True)
    r = proc.complete([tool("ssh-keygen"), "-q", "-t", "ed25519", "-N", "", "-C", f"chip@{socket.gethostname()}",
                       "-f", OWN_KEY], timeout=30)
    return OWN_KEY if r.returncode == 0 and own_key() else None
