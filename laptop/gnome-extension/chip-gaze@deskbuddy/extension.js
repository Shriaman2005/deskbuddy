import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const NAME = 'org.deskbuddy.Gaze';
const PATH = '/org/deskbuddy/Gaze';
const XML = `
<node>
  <interface name="${NAME}">
    <method name="Pointer"><arg type="i" direction="out"/><arg type="i" direction="out"/></method>
    <method name="Monitors"><arg type="s" direction="out"/></method>
    <method name="Start"/>
    <signal name="Moved"><arg type="i"/><arg type="i"/></signal>
  </interface>
</node>`;

const POLL_MS = 100;       // how often the pointer is looked at while the bridge keeps asking
const MIN_MOVE = 3;        // px; smaller moves are not reported
const KEEP_MS = 15000;     // the timer stops by itself this long after the last Start()

export default class ChipGaze extends Extension {
    enable() {
        this._timer = 0;
        this._lastStart = 0;
        this._last = null;
        this._dbus = Gio.DBusExportedObject.wrapJSObject(XML, this);
        this._dbus.export(Gio.DBus.session, PATH);
        this._owner = Gio.bus_own_name_on_connection(Gio.DBus.session, NAME,
            Gio.BusNameOwnerFlags.NONE, null, null);
    }

    disable() {
        this._stop();
        if (this._owner) {
            Gio.bus_unown_name(this._owner);
            this._owner = 0;
        }
        this._dbus?.unexport();
        this._dbus = null;
        this._last = null;
    }

    Pointer() {
        const [x, y] = global.get_pointer();
        return [x, y];
    }

    Monitors() {
        const primary = Main.layoutManager.primaryIndex;
        return JSON.stringify(Main.layoutManager.monitors.map((m, i) =>
            ({x: m.x, y: m.y, w: m.width, h: m.height, primary: i === primary})));
    }

    Start() {
        this._lastStart = GLib.get_monotonic_time();
        if (this._timer)
            return;
        const [x, y] = global.get_pointer();
        this._last = [x, y];
        this._timer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, POLL_MS, () => this._tick());
    }

    _tick() {
        if (!this._dbus || GLib.get_monotonic_time() - this._lastStart > KEEP_MS * 1000) {
            this._timer = 0;
            return GLib.SOURCE_REMOVE;
        }
        const [x, y] = global.get_pointer();
        if (Math.hypot(x - this._last[0], y - this._last[1]) >= MIN_MOVE) {
            this._last = [x, y];
            this._dbus.emit_signal('Moved', GLib.Variant.new('(ii)', [x, y]));
        }
        return GLib.SOURCE_CONTINUE;
    }

    _stop() {
        if (this._timer) {
            GLib.source_remove(this._timer);
            this._timer = 0;
        }
    }
}
