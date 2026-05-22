# Archive layout & family → raw-file mapping

```
archive/
├── manifest.json                          # GPU inventory, VFIO, NVSwitch, schema_version
├── report.ndjson                          # per-artifact status (success|partial|missing)
├── triage/
│   ├── _data/
│   │   ├── summary.json                   # Tier-1: all classified findings
│   │   ├── xid_events.json                # parsed Xid/SXid with codes
│   │   ├── thermal_anomalies.json
│   │   ├── power_events.json
│   │   ├── ecc_events.json
│   │   ├── memory_errors.json
│   │   └── nvlink_errors.json
│   └── (analyzer intermediate state)
├── logs/
│   ├── journal_kernel.{ndjson,txt}        # ← Tier-2 for: xid, ecc, mce, lockup
│   ├── journal_errors.{ndjson,txt}        # ← Tier-2 for: firmware/driver
│   ├── journal_docker.{ndjson,txt}        # container runtime
│   ├── journal_containerd.{ndjson,txt}    # k8s/containerd
│   ├── dmesg.txt                          # boot-time, PCIe AER, link resets
│   └── boot_history.txt
├── nvidia/
│   ├── xid_errors.txt                     # ← Tier-2 for: xid_events (usually empty)
│   ├── gpu_summary.txt
│   ├── persistenced_status.txt
│   ├── pci_devices.txt
│   └── nvidia-smi-{q,csv,nvlink,topo,pmon}.txt
├── hardware/
│   ├── thermal_sensors.json               # ← Tier-2 for: thermal_anomalies
│   ├── pcie_link_status.json
│   ├── pcie_aer_errors.json               # ← Tier-2 for: power_events (PCIe AER)
│   ├── edac_status.json                   # ← Tier-2 for: ecc_events
│   ├── rasdaemon_errors.txt
│   ├── nvme_list.txt
│   ├── nvme_error_log.txt
│   ├── smart_devices.txt
│   ├── kernel_tainted.txt
│   ├── memory.txt
│   ├── memory_detailed.txt
│   └── hugepages.txt
├── dcgm/
│   ├── dcgmi_discovery.txt
│   ├── dcgmi_health.txt
│   ├── dcgmi_stats.txt
│   └── dcgmi_counters.txt
├── ipmi/
│   ├── sel_events.txt                     # IPMI System Event Log
│   ├── sel_info.txt
│   ├── sdr_list.txt
│   ├── bmc_info.txt
│   └── chassis_status.txt
├── services/
│   ├── all_services.txt
│   ├── failed_services.txt
│   ├── key_services.txt
│   └── status_<unit>.txt                  # per-unit detail
├── docker/
│   ├── docker_ps_all.txt
│   ├── docker_info.txt
│   ├── docker_version.txt
│   ├── docker_networks.txt
│   ├── docker_df.txt
│   ├── vllm_logs/<name>_{logs,stats}.txt   # vLLM containers
│   └── diagnostic/<name>_logs.txt          # tagged diag containers
├── hypervisor/
│   ├── virsh_list.txt
│   ├── virsh_domstats.txt
│   ├── virsh_nodeinfo.txt
│   ├── kvm_modules.txt
│   ├── kvm_module_params.txt
│   ├── vfio_bindings.txt                  # check before SXid interpretation
│   ├── iommu_groups.txt
│   └── virsh_version.txt
├── ovs/
│   ├── ovs_show.txt
│   ├── ovs_bridges.txt
│   ├── ovs_datapath.txt
│   ├── ovs_coverage.txt
│   ├── ovs_memory.txt
│   ├── ovs_version.txt
│   └── ovs_stale_sockets.txt
├── network/
│   ├── ip_{addr,link,route,neigh}.txt
│   ├── ss_{all,listen}.txt
│   ├── {iptables,nftables,ufw_status,firewalld_zones}.txt
│   ├── {ibstat,ibstatus,ibv_devinfo,rdma_link,perfquery}.txt
│   ├── nic_hw_errors.txt
│   ├── devlink_health.json
│   ├── nm_*.txt, netplan_*.txt, networkctl_*.txt, resolvectl_*.txt
│   └── ... (40+ files)
├── packages/
│   ├── {nvidia,docker,kernel}_packages.txt
│   ├── apt_sources.txt, apt_held.txt
│   ├── dpkg_recent.txt, dnf_history.txt
│   ├── pip_packages.txt
│   └── all_packages.txt
├── processes/
│   ├── ps_aux.txt
│   ├── ps_tree.txt
│   └── top_snapshot.txt
└── system/
    ├── cpu.txt, memory.txt, sysctl.txt, ulimits.txt
    ├── lsmod.txt, kernel_cmdline.txt, kernel_tainted.txt
    ├── crash_dumps.txt, date.txt, uname.txt, uptime.txt
    ├── hostname.txt, hostname_file.txt
    ├── overview.txt, limits_conf.txt
    └── nvidia_modules.txt
```

## Family → trustworthy source priority

```
family            tier1 (parsed)                      tier2 (raw fallback)
xid               triage/_data/xid_events.json        logs/journal_kernel.ndjson, nvidia/xid_errors.txt
thermal           triage/_data/thermal_anomalies.json hardware/thermal_sensors.json, dcgm/dcgmi_health.txt
power_pcie_aer    triage/_data/power_events.json     hardware/pcie_aer_errors.json, dmesg.txt
ecc               triage/_data/ecc_events.json       hardware/edac_status.json, hardware/rasdaemon_*.txt
memory            triage/_data/memory_errors.json    hardware/memory_detailed.txt, hardware/edac_status.json
nvlink            triage/_data/nvlink_errors.json    nvidia/nvidia-smi-nvlink.txt, network/perfquery.txt
ipmi              (none — parse raw)                 ipmi/sel_events.txt
services          (none — parse raw)                 services/failed_services.txt + status_<unit>.txt
hypervisor        (none — parse raw)                 hypervisor/virsh_*.txt
container         (none — parse raw)                 docker/docker_*.txt, journal_docker.ndjson
firewall          (none — parse raw)                 network/{iptables,nftables,ufw_status,firewalld_zones}.txt
```
