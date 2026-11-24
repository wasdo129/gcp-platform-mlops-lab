import "serving-cluster-read" as $legacy;

# Terraform 1.17.2 / Google 7.46.1 read-side shapes observed on this lab.
# Compare entire resource values after canonicalizing only approved paths.
def normalize_firewall:
  .source_tags |= (if . == null then [] else . end)
  | .source_service_accounts |= (if . == null then [] else . end)
  | .target_service_accounts |= (if . == null then [] else . end);

def normalize_cpu:
  .node_config[0].resource_manager_tags |= (if . == null then {} else . end)
  | .node_config[0].storage_pools |= (if . == null then [] else . end);

def known_serving_drift($project; $zone; $cluster):
  all((.resource_drift // [])[];
    . as $entry
    | .mode == "managed"
      and .provider_name == "registry.terraform.io/hashicorp/google"
      and .change.actions == ["update"]
      and ((.change.replace_paths // []) | length == 0)
      and ([.change.after_unknown // {} | .. | select(. == true)] | length == 0)
      and (
        .change.before as $before | .change.after as $after
        | if $entry.address == "google_compute_firewall.cnpg_webhook" then
            $after.project == $project and $after.name == ($cluster + "-cnpg-webhook")
            and ($before | normalize_firewall) == $after
          elif $entry.address == "google_container_node_pool.cpu" then
            $after.project == $project and $after.location == $zone
            and $after.cluster == $cluster and $after.name == "cpu"
            and ($before | normalize_cpu) == $after
          elif $entry.address == "google_container_cluster.lab" then
            $after.project == $project and $after.location == $zone and $after.name == $cluster
            and $before.node_config == [] and $before.node_pool == []
            and $after.node_config == $legacy[0].node_config
            and $after.node_pool == ($legacy[0] | .node_config as $config | .node_pool | map(.node_config = $config))
            and ($before | del(.node_config, .node_pool)) == ($after | del(.node_config, .node_pool))
          else false end
      )
  );

# Baseline validation is separate from the one-change create/delete guard.
def serving_baseline_clean($project; $zone; $cluster):
  (.errored == false) and (.complete == true)
  and ((.deferred_changes // []) | length == 0)
  and ((.action_invocations // []) | length == 0)
  and ((.deferred_action_invocations // []) | length == 0)
  and all(.resource_changes[];
    .previous_address == null and .change.importing == null
    and (.mode != "managed" or .change.actions == ["no-op"]))
  and all((.output_changes // {})[]; .actions == ["no-op"])
  and known_serving_drift($project; $zone; $cluster);
