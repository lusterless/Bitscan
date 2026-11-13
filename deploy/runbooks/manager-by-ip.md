# Reach the manager by IP address

This runbook moves existing agents from a manager host name (`mgr.example`) to the manager's IP addresses. It also covers a manager reached at two addresses, for example an internal one and a public one. The agent and manager code need no change: `manager_url` accepts `https://<ip>[:port]`, and the agent checks that the manager's certificate lists that IP.

The examples use these addresses. Replace them with yours:

| Agents | Address they use | `manager_url` |
|---|---|---|
| Inside your network | `10.0.0.5`, port `8443` (the manager's own address) | `https://10.0.0.5:8443` |
| Outside | `203.0.113.10`, port `443` (a public address that NAT forwards to the manager) | `https://203.0.113.10` |

**The port is part of the address.** A NAT or load balancer often forwards a different port, as in the example above, where public port 443 goes to the manager's 8443. Use the port that works in the test of section 6 or 7. A URL without a port means 443.

Each step says where to run it:

| Label | Machine |
|---|---|
| **MANAGER** | the Bitscan manager host |
| **CA** | the machine that holds your private CA (`manager-ca.pem` and `manager-ca.key`, `manager-install.md` section 1) |
| **AGENT-IN** | one agent host inside your network |
| **AGENT-OUT** | one agent host outside, which reaches the public address |
| **ADMIN** | your workstation, which can SSH to every agent host |
| **BROWSER** | any PC you use for the web UI |

Nothing changes for agents until section 8. Until then every agent still uses `mgr.example`, and the new certificate still lists that name.

Public certificate authorities rarely issue certificates for IP addresses, and never for private ones. This runbook uses your own CA, as in [`manager-install.md`](manager-install.md) section 1. Keep `manager-ca.key` off every Bitscan host and outside any git repository: whoever holds it can issue a certificate that every agent trusts.

## 1. Check the manager's addresses (MANAGER)

```sh
ip -br addr
sudo grep BITSCAN_LISTEN /etc/bitscan/manager.env
```

- **`BITSCAN_LISTEN`:** with no line, or `0.0.0.0:8443`, the manager answers on every address, and nothing needs changing. If it is bound to a single address, set `BITSCAN_LISTEN=0.0.0.0:8443` with `sudoedit /etc/bitscan/manager.env`. The restart in section 5 applies it.
- **The public address:** if `ip -br addr` does not list it, it is a NAT or cloud public address. The firewall or cloud provider must forward it to the manager, for example public `203.0.113.10:443` to `10.0.0.5:8443`. Allow only the networks your outside agents come from: the web UI and the API answer on the same port.

## 2. Make a certificate request from the existing key (MANAGER)

The key stays the same, so agents that pin it with `manager_spki_sha256` keep working.

```sh
sudo openssl req -new -key /etc/bitscan/secrets/tls.key -subj "/CN=bitscan-manager" -out ~/manager-ip.csr
```

The common name (CN) does not matter: the agent checks only the certificate's subject alternative names. Copy `~/manager-ip.csr` to **CA**.

## 3. Sign it with every address and the old name (CA)

In the folder that holds `manager-ca.pem`, `manager-ca.key` and `manager-ip.csr`:

```sh
printf 'subjectAltName=IP:10.0.0.5,IP:203.0.113.10,DNS:mgr.example\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=serverAuth\n' > manager-ip.ext
openssl x509 -req -in manager-ip.csr -CA manager-ca.pem -CAkey manager-ca.key -CAcreateserial \
    -days 397 -extfile manager-ip.ext -out manager-ip.crt
openssl x509 -in manager-ip.crt -noout -ext subjectAltName
```

The last command must list `DNS:mgr.example` and an `IP Address:` entry for every address. Keeping `mgr.example` lets anything that still uses the name keep working, and lets you switch back (section 13). Copy only `manager-ip.crt` to **MANAGER**.

## 4. Check the certificate matches the manager's key (MANAGER)

```sh
cmp <(openssl x509 -in ~/manager-ip.crt -noout -pubkey) <(sudo openssl pkey -in /etc/bitscan/secrets/tls.key -pubout)
```

It must print nothing. Anything else means the certificate was made from a different request: stop.

## 5. Install the certificate (MANAGER)

```sh
sudo cp /etc/bitscan/secrets/tls.crt /etc/bitscan/secrets/tls.crt.bak
sudo cp ~/manager-ip.crt /etc/bitscan/secrets/tls.crt
sudo systemctl restart bitscan-manager
systemctl is-active bitscan-manager
```

The last command must print `active`. If it does not, put the old certificate back:

```sh
sudo cp /etc/bitscan/secrets/tls.crt.bak /etc/bitscan/secrets/tls.crt
sudo systemctl restart bitscan-manager
sudo journalctl -u bitscan-manager -n 30 --no-pager
```

## 6. Test the internal address (AGENT-IN)

```sh
sudo grep -E 'manager_url|ca_file|manager_spki' /etc/bitscan/agent.yaml
openssl s_client -connect 10.0.0.5:8443 -CAfile /etc/bitscan/ca.pem \
    -verify_ip 10.0.0.5 -verify_return_error -brief </dev/null
```

Use the `ca_file` path that the first command prints. A good result shows `Peer certificate: CN = bitscan-manager` (the new certificate) and `Verification: OK`. The line `Can't use SSL_get_servername` is harmless: a connection by IP sends no server name. If verification fails, stop here; no agent has changed yet.

## 7. Test the public address (AGENT-OUT)

```sh
openssl s_client -connect 203.0.113.10:443 -CAfile /etc/bitscan/ca.pem \
    -verify_ip 203.0.113.10 -verify_return_error -brief </dev/null
```

Same result expected. If the connection is refused or times out, try the other port (443 or 8443): the forwarding rule decides which one works from outside. The port that works goes into `manager_url`.

## 8. Switch one internal agent (AGENT-IN)

```sh
sudo sed -i "s|^manager_url:.*|manager_url: 'https://10.0.0.5:8443'|" /etc/bitscan/agent.yaml
sudo systemctl restart bitscan-agent
sudo journalctl -u bitscan-agent -n 20 --no-pager
```

The agent reads `manager_url` at start-up. It keeps its token and agent id, does not enrol again, and needs no approval. `sed -i` keeps the file's owner and mode (`root:bitscan`, 0640).

## 9. Switch one outside agent (AGENT-OUT)

```sh
sudo sed -i "s|^manager_url:.*|manager_url: 'https://203.0.113.10'|" /etc/bitscan/agent.yaml
sudo systemctl restart bitscan-agent
sudo journalctl -u bitscan-agent -n 20 --no-pager
```

## 10. Check both hosts are online (BROWSER)

Wait about 5 minutes (one heartbeat). On the **Hosts** page, both hosts must be **online** with a new heartbeat time. If one is not, undo it on that host with section 8's commands and `https://mgr.example:8443`.

## 11. Switch every other agent (ADMIN)

Write `hosts-internal.txt` and `hosts-external.txt`, one SSH host name per line, without the two hosts already switched. The function takes the full `manager_url`, port included:

```sh
switch() {
  while read -r h; do
    echo "== $h"
    ssh -n "$h" "sudo sed -i \"s|^manager_url:.*|manager_url: '$2'|\" /etc/bitscan/agent.yaml && sudo systemctl restart bitscan-agent && systemctl is-active bitscan-agent"
  done < "$1"
}
switch hosts-internal.txt https://10.0.0.5:8443
switch hosts-external.txt https://203.0.113.10
```

Each host must print `active`. About 5 minutes later, no host may be offline on the **Hosts** page.

`manager_url` holds one address and the agent has no fallback. A host that moves between networks needs the address that works from both, usually the public one.

## 12. Web UI and new agents (BROWSER, new hosts)

- **Web UI:** open `https://10.0.0.5:8443` inside or `https://203.0.113.10` outside. A browser that trusted `manager-ca.pem` for `mgr.example` trusts the new certificate too. Sign in again: a session belongs to the address it was started on.
- **New agents:** preseed the address that host reaches, with the same CA file (`agent-install.md` section 3), for example `bitscan-agent bitscan/manager_url string https://203.0.113.10`.
- **Outside hosts:** pin the manager's key (`bitscan/manager_spki_sha256`; the value comes from [`manager-install.md`](manager-install.md) section 1), give their enrolment token `allowed_cidrs` for their public ranges, and leave `auto_approve` off. Behind NAT, the source address the manager sees may be the router's.

## 13. Switch back, clean up and renew (ADMIN, MANAGER)

- **Switch back:** run section 11's function with `https://mgr.example:8443` for both lists. The certificate still lists the name, so the manager needs no change.
- **Clean up:** after a week without problems, on MANAGER: `sudo rm /etc/bitscan/secrets/tls.crt.bak ~/manager-ip.csr ~/manager-ip.crt`. Lines for `mgr.example` in agents' `/etc/hosts` can go once every host has been online by IP for a day, unless something else uses the name.
- **Renew:** the certificate lasts 397 days. Repeat sections 2 to 5 with the same `subjectAltName` line. If an address changes, change that line and switch the affected agents again (sections 6 to 11).
- **A new manager key** (for example after the old one leaked): make the request with a new key instead of section 2's, install both files as in [`manager-operations.md`](manager-operations.md) section 2, and change `manager_spki_sha256` on every pinned agent first ([`agent-install.md`](agent-install.md) section 7). After a CA change, every agent also needs the new CA file.
