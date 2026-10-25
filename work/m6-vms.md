# M6 test VMs (Hyper-V)

Prepared by `vm-builder` on 2026-10-25. Nothing here lives in the repo; all files are under `C:\Users\kaiquan.koh\BitscanVMs\`.

## Status

**Created, never booted.** Both VMs are `Off`. When they were created the host had only 0.5 to 2 GB of RAM free or available (the WSL VM held about 4.9 GB), below the 6 GB threshold. Because of that, first boot, SSH, cgroup v2 and the `clean` checkpoint are **not verified yet**. Follow "First start" below once about 6 GB is free.

## VMs

| VM | Guest OS | Generation | vCPU | RAM | Disk | Static MAC |
|---|---|---|---|---|---|---|
| `bitscan-u2204` | Ubuntu 22.04 LTS amd64 | 2, Secure Boot `MicrosoftUEFICertificateAuthority` | 2 | 2 GB static (dynamic memory off) | 20 GB dynamic VHDX | `00-15-5D-0B-22-04` |
| `bitscan-u2404` | Ubuntu 24.04 LTS amd64 | 2, Secure Boot `MicrosoftUEFICertificateAuthority` | 2 | 2 GB static (dynamic memory off) | 20 GB dynamic VHDX | `00-15-5D-0B-24-04` |

- Switch: `Default Switch` (NAT, gives internet access for apt). Automatic checkpoints are off. Automatic start is off, and the VMs shut down when the host stops.
- Disks: `C:\Users\kaiquan.koh\BitscanVMs\vhd\<vm>.vhdx`. VM config: `C:\Users\kaiquan.koh\BitscanVMs\vms\`.
- The cloud-init NoCloud seed ISO (label `cidata`) is attached as a DVD: `C:\Users\kaiquan.koh\BitscanVMs\seed\<vm>-seed.iso`. It creates user `bstester` (sudo NOPASSWD, password locked, key only), sets `ssh_pwauth: false`, `disable_root: true`, the hostname and `package_upgrade: false`. On first boot, growpart expands the root filesystem to 20 GB. The generic cloud images' default kernel is cgroup v2 with systemd.
- Nothing else is installed. In particular `hyperv-daemons` / `linux-cloud-tools` is not installed, so Hyper-V cannot see the guest IP (see "IP addresses").

## Images (verified)

These are the official release images (not daily), saved in `C:\Users\kaiquan.koh\BitscanVMs\images\<ver>\`. Each image was checked against that release's `SHA256SUMS`, and `SHA256SUMS.gpg` gave a good signature from "UEC Image Automatic Signing Key" (key `D2EB44626FDDC30B513D5BB71A5D6C4C7DB87C81`, `/usr/share/keyrings/ubuntu-cloudimage-keyring.gpg`).

| File | Release serial | SHA-256 |
|---|---|---|
| `ubuntu-22.04-server-cloudimg-amd64.img` | `releases/22.04/release-20261020` | `2099e63da0b822ef8e05e3d596c1b402eaaae658fc08ab919cb8495bfcdc488b` |
| `ubuntu-24.04-server-cloudimg-amd64.img` | `releases/24.04/release-20261017` | `04e8f2461a16a44e78a370284471f29616cdd9baf1893df25807b71f985b6c94` |

How they were converted: `qemu-img convert -O vhdx -o subformat=dynamic` in WSL, then Windows `Convert-VHD -VHDType Dynamic` (so the file is not sparse), then `Resize-VHD -SizeBytes 20GB`.

## SSH key

- Windows: `C:\Users\kaiquan.koh\BitscanVMs\ssh\bitscan_vm` (+ `.pub`). The ACL grants access only to `BITDEER-INC\kaiquan.koh`, with inheritance removed.
- WSL Ubuntu-24.04: `/root/.ssh/bitscan_vm` (mode 600) and `/root/.ssh/bitscan_vm.pub`.
- Type ed25519, no passphrase, comment `bitscan-m6-vm-tester`, fingerprint `SHA256:h2pCarTF81KJMArkUWz0ocARoRpLPxctKytn2cGTcUA`. Never copy it into a repo.

## Start, stop, checkpoint (PowerShell, no elevation needed)

```powershell
Start-VM bitscan-u2204, bitscan-u2404
Stop-VM  bitscan-u2204, bitscan-u2404            # clean ACPI shutdown
Get-VM   bitscan-u*                               # state
Checkpoint-VM -Name bitscan-u2204 -SnapshotName clean
Get-VMSnapshot -VMName bitscan-u2204
Restore-VMSnapshot -VMName bitscan-u2204 -Name clean -Confirm:$false   # back to a clean host
```

The `clean` checkpoint does **not exist yet**. Take it after the first boot is verified, with the VM shut down (`Stop-VM`, then `Checkpoint-VM`), so it is a standard checkpoint of a powered-off disk.

## First start (still to do)

1. Check memory first: `(Get-Counter '\Memory\Available MBytes').CounterSamples[0].CookedValue`. You need about 6 GB available.
2. Run `Start-VM bitscan-u2204, bitscan-u2404` and wait about 1 to 2 minutes for cloud-init.
3. Find each IP (next section), then run the SSH check from Git Bash and from WSL (see "SSH").
4. Check that cloud-init finished: `ssh ... 'cloud-init status --wait; stat -fc %T /sys/fs/cgroup'`. Expect `status: done` and `cgroup2fs`.
5. `Stop-VM`, then `Checkpoint-VM -SnapshotName clean`, on each VM.
6. Optional: `Remove-VMDvdDrive` the seed ISO after the checkpoint. cloud-init only runs once per `instance-id`.

## IP addresses

The IPs are not known yet; the VMs have not booted. Default Switch gives out DHCP addresses from the host's `vEthernet (Default Switch)` subnet, which was `172.31.0.1/20` when the VMs were created. **That subnet changes when Windows reboots**, so look the IP up again after every host reboot:

```powershell
# Via ARP, matched on the static MAC (works without Hyper-V guest daemons)
Get-NetNeighbor -InterfaceAlias 'vEthernet (Default Switch)' |
  Where-Object LinkLayerAddress -in '00-15-5D-0B-22-04','00-15-5D-0B-24-04' |
  Format-Table IPAddress, LinkLayerAddress
# Or by name, through the Default Switch DNS (Windows only)
Resolve-DnsName bitscan-u2204.mshome.net
```

`Get-VMNetworkAdapter -VMName <vm>` will show **no IP**, because the KVP daemon is not installed. The VM console (`vmconnect localhost bitscan-u2204`) also shows the cloud-init `ci-info` network table with the IP on first boot. You cannot log in on the console because the account has no password.

## SSH

Git Bash:

```bash
ssh -i /c/Users/kaiquan.koh/BitscanVMs/ssh/bitscan_vm -o StrictHostKeyChecking=accept-new \
  bstester@<ip> 'uname -a; stat -fc %T /sys/fs/cgroup; systemctl is-system-running'
```

WSL (`Ubuntu-24.04`, runs as root):

```bash
ssh -i /root/.ssh/bitscan_vm -o StrictHostKeyChecking=accept-new bstester@<ip> '...'
```

## Known quirks

- **WSL to VM reachability is not verified and probably blocked.** WSL runs in NAT mode (no `.wslconfig`, subnet `172.18.208.0/20`) on a separate internal switch. From WSL, the host's Default Switch address `172.31.0.1` does not answer ping. Windows does not route between the WSL and Default Switch vEthernet adapters by default. Options that need no firewall or admin change, not yet tested:
  - Tester to VM: from WSL, call the Windows client through interop: `ssh.exe -i 'C:\Users\kaiquan.koh\BitscanVMs\ssh\bitscan_vm' bstester@<ip> ...`
  - Agent on VM to manager in WSL: WSL publishes its listening ports on Windows `localhost`, which the VMs cannot reach. A per-session tunnel from Git Bash works without admin: `ssh -i ... -N -R 8443:localhost:8443 bstester@<ip>`. The agent on the VM then uses `https://localhost:8443`, so the manager's TLS certificate must cover `localhost`.
  - Changes that need `main` or user approval first: `networkingMode=mirrored` in `%UserProfile%\.wslconfig` (restarts WSL for every tester), `netsh interface portproxy` or IP forwarding (admin), and firewall rules.
- The Default Switch subnet, and so the VM IPs, change after a host reboot. Host keys stay the same, so `known_hosts` entries keyed by the old IP become stale. Use `-o StrictHostKeyChecking=accept-new` and remove old entries with `ssh-keygen -R <old-ip>`.
- Memory: the two VMs need 4 GB of static RAM together. Shut WSL down (`wsl --shutdown`) or cap it with `memory=` in `.wslconfig` if starting them fails with an out-of-memory error.
- Time sync and IP reporting through Hyper-V integration services need `hyperv-daemons`, which is deliberately not installed. Guest time comes from systemd-timesyncd over the internet.
