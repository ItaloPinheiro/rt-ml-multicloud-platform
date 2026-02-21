import yaml

# 1. Update ops/k8s/base/kustomization.yaml to include generators
with open("ops/k8s/base/kustomization.yaml", "r") as f:
    kust = yaml.safe_load(f)

if "configMapGenerator" not in kust:
    kust["configMapGenerator"] = []

# Remove old generators if they exist so we don't duplicate
kust["configMapGenerator"] = [
    g for g in kust["configMapGenerator"] 
    if g.get("name") not in ["grafana-dashboards", "grafana-config", "prometheus-config"]
]

kust["configMapGenerator"].extend([
    {
        "name": "prometheus-config",
        "namespace": "ml-pipeline",
        "files": [
            "../../monitoring/prometheus/prometheus.yml",
            "../../monitoring/prometheus/alerts/alert_rules.yml",
            "../../monitoring/prometheus/rules/recording_rules.yml"
        ]
    },
    {
        "name": "grafana-config",
        "namespace": "ml-pipeline",
        "files": [
            "../../monitoring/grafana/datasources/datasources.yaml",
            "../../monitoring/grafana/dashboards/dashboards.yaml"
        ]
    },
    {
        "name": "grafana-dashboards",
        "namespace": "ml-pipeline",
        "files": [
            "../../monitoring/grafana/dashboards/model-performance.json",
            "../../monitoring/grafana/dashboards/feature-store.json",
            "../../monitoring/grafana/dashboards/system-resources.json",
            "../../monitoring/grafana/dashboards/data-ingestion.json",
            "../../monitoring/grafana/dashboards/error-tracking.json",
            "../../monitoring/grafana/dashboards/apps-uptime.json"
        ]
    }
])

# generatorOptions to prevent hashed names which break deployments that hardcode them
if "generatorOptions" not in kust:
    kust["generatorOptions"] = {"disableNameSuffixHash": True}

with open("ops/k8s/base/kustomization.yaml", "w") as f:
    yaml.dump(kust, f, default_flow_style=False, sort_keys=False)

# 2. Update monitoring.yaml Deployments and strip out hardcoded ConfigMaps
with open("ops/k8s/base/monitoring.yaml", "r") as f:
    docs = list(yaml.safe_load_all(f))

# Filter out old hardcoded ConfigMaps since they are now generated
docs = [d for d in docs if not (d and d.get("kind") == "ConfigMap" and d.get("metadata", {}).get("name") in ["grafana-config", "prometheus-config", "grafana-dashboards"])]

for doc in docs:
    if not doc: continue
    
    if doc.get("kind") == "Deployment":
        if doc.get("metadata", {}).get("name") == "grafana":
            container = doc["spec"]["template"]["spec"]["containers"][0]
            # Clean old mounts
            container["volumeMounts"] = [vm for vm in container["volumeMounts"] if "grafana-config" not in vm["name"] and "grafana-dashboards" not in vm["name"]]
            
            # Map the exact files we just generated into the provisioner
            container["volumeMounts"].extend([
                {
                    "name": "grafana-config",
                    "mountPath": "/etc/grafana/provisioning/datasources/datasources.yaml",
                    "subPath": "datasources.yaml"
                },
                {
                    "name": "grafana-config",
                    "mountPath": "/etc/grafana/provisioning/dashboards/dashboards.yaml",
                    "subPath": "dashboards.yaml"
                },
                {
                    "name": "grafana-dashboards",
                    "mountPath": "/var/lib/grafana/dashboards/"
                }
            ])
            
            # Update volumes array
            volumes = doc["spec"]["template"]["spec"]["volumes"]
            volumes = [v for v in volumes if "grafana-dashboards" not in v["name"]]
            
            volumes.append({
                "name": "grafana-dashboards",
                "configMap": {"name": "grafana-dashboards"}
            })
            
            # Make sure liveness/readiness probes exist for zero-downtime updates
            container["readinessProbe"] = {
                "httpGet": {"path": "/api/health", "port": 3000},
                "initialDelaySeconds": 15,
                "periodSeconds": 10
            }
            doc["spec"]["template"]["spec"]["volumes"] = volumes

        elif doc.get("metadata", {}).get("name") == "prometheus":
             container = doc["spec"]["template"]["spec"]["containers"][0]
             # Update args to include recording rules
             # Prometheus auto-reloads if --web.enable-lifecycle is on (which it is)
             # But we need to make sure the args haven't stripped it
             args = container.get("args", [])
             if "--web.enable-lifecycle" not in args:
                 args.append("--web.enable-lifecycle")
             container["args"] = args
             
             container["readinessProbe"] = {
                "httpGet": {"path": "/-/ready", "port": 9090},
                "initialDelaySeconds": 10,
                "periodSeconds": 10
             }

with open("ops/k8s/base/monitoring.yaml", "w") as f:
    yaml.dump_all([d for d in docs if d], f, default_flow_style=False, sort_keys=False)
    
print("Updated Kustomization and Monitoring manifests successfully.")
