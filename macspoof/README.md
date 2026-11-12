# macspoof

A MAC address spoofer for Linux and macOS, with both a command line interface
and a GTK4 desktop application.

![macspoof GUI](data/com.github.macspoof.MacSpoof.svg)

## Features

- List every network interface with its current and factory MAC address
- Set a specific MAC address
- Generate a random MAC address — either locally administered or keeping the
  original vendor prefix
- Restore the factory MAC address
- Optionally persist the address across reconnects (NetworkManager)
- Optionally apply the address automatically at boot (systemd)

## Install

```bash
cd macspoof
make install      # creates .venv and installs the package
```

Or install it for your user:

```bash
pip install --user .      # add --break-system-packages on PEP 668 distros
pipx install .            # recommended on Arch
```

Or run it straight from the source tree with no install at all:

```bash
python3 -m macspoof list
```

After `pip install --user .` the commands land in `~/.local/bin`, which may
not be on your `PATH`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

## GUI

```bash
macspoof-gui
```

The GUI lists your interfaces, lets you pick one, and shows the spoofing
actions. It runs as your normal user and asks for authentication through the
desktop's polkit agent when a change is actually made.

For the best experience install the privileged helper once:

```bash
sudo macspoof-install-helper
```

That installs a root-owned helper at `/usr/local/libexec/macspoof-helper` and
a polkit action at `/usr/share/polkit-1/actions/org.macspoof.policy`. With it
in place the polkit agent can remember the authorisation for the session
instead of prompting for every single change.

Without the system helper the GUI still works — it falls back to a private
temporary wrapper script, which just means authenticating each time.

To add it to your application menu:

```bash
./install-desktop.sh
```

### GUI options

| Control | What it does |
| --- | --- |
| Custom MAC address | Type an exact address and apply it |
| Randomize → Locally administered | A unique random address that cannot clash with a real vendor OUI |
| Randomize → Keep vendor prefix | A random address that impersonates the original manufacturer |
| Restore | Go back to the address burned into the hardware |
| Persist across reconnects | Re-apply the address when the connection is re-established |

Interfaces whose MAC differs from the factory address are marked **spoofed**.

## CLI

```
macspoof list                              show every interface and its MACs
macspoof current -i enp34s0                print the current MAC
macspoof set AA:BB:CC:DD:EE:FF -i enp34s0 set a specific MAC
macspoof random -i enp34s0                 assign a random locally administered MAC
macspoof random -i enp34s0 --keep-vendor   random MAC that keeps the vendor OUI
macspoof restore -i enp34s0                go back to the factory MAC
macspoof random -i enp34s0 --persist       survive reconnects (NetworkManager)
macspoof install -i enp34s0                systemd unit applying a MAC at boot
macspoof uninstall                         remove that unit
```

Changing a MAC requires root, so run it with `sudo`:

```bash
sudo macspoof random -i enp34s0
```

## How it works

**Linux** — the interface is brought down, `ip link set dev <if> address <mac>`
is applied, and the interface is brought back up. The factory MAC is read from
`ethtool -P`, so `restore` always returns to the real hardware address.

**Random MACs** are locally administered (bit `0x02` of the first octet is
forced on) and unicast (bit `0x01` forced off). That guarantees the address
cannot collide with a real vendor OUI and cannot be a multicast address.
`--keep-vendor` preserves the original three-byte vendor prefix verbatim so
the address impersonates that vendor; note that such an address is no longer
locally administered, since the vendor prefix is left untouched.

**The GUI** never runs as root. Privileged work is delegated to a small helper
through `pkexec`, so the polkit agent shows a normal authentication prompt.
The helper validates the interface name and the MAC address before touching
anything.

**Persistence** has two layers:

- `--persist` writes `cloned-mac-address` into the active NetworkManager
  profile, so the spoofed address is re-applied on every reconnect. The
  property group differs between NetworkManager versions (`802-3-ethernet` on
  current releases, `802-11-ethernet` on older ones), so all known spellings
  are tried until one is accepted. Restoring sets it back to `permanent`,
  which makes NetworkManager use the real hardware address again.
- `macspoof install` writes a systemd unit that re-applies the address at boot
  and restores the factory MAC on shutdown. The unit calls the `macspoof`
  binary by absolute path, so it keeps working regardless of `PATH`.

## Notes

- Some Wi-Fi drivers and corporate APs reject locally administered addresses
  or enforce MAC-based access control (802.11e/PMF). If the network drops right
  after the change, the AP is the one refusing you. Use the "Keep vendor
  prefix" mode in that case.
- Bridged and virtual interfaces (`virbr0`, `veth*`, `docker0`) are managed by
  their parent and usually refuse MAC changes.
- On Linux, changing the MAC of an interface managed by NetworkManager can be
  reverted when NM re-activates the connection — use `--persist` in that case.

## Development

```bash
make test      # run the test suite
make run ARGS="list"
```

The GUI tests drive the GTK widgets directly, so they do not need a
compositor.

## Legal

Spoofing a MAC on hardware you own is fine for privacy, lab work and testing.
Using it to evade network policy or attribution on someone else's network is
not.

## License

MIT
