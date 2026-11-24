# Accept one exact serving-pool change and only reviewed read-side differences.
include "serving-drift";
def serving_identity:
  .project == $project and .location == $zone and .cluster == $cluster and .name == "serving";

(.errored == false) and (.complete == true) and (.applyable == true)
and ((.deferred_changes // []) | length == 0)
and ((.action_invocations // []) | length == 0)
and ((.deferred_action_invocations // []) | length == 0)
and all(.resource_changes[]; .previous_address == null and .change.importing == null)
and all((.output_changes // {})[]; .actions == ["no-op"])
and known_serving_drift($project; $zone; $cluster)
and (
  [.resource_changes[] | select(.mode == "managed" and .change.actions != ["no-op"])]
  | length == 1
  and .[0].address == "google_container_node_pool.serving[0]"
  and .[0].change.actions == [$operation]
  and (.[0].change | if $operation == "create" then
    .before == null and (.after | serving_identity)
  elif $operation == "delete" then
    .after == null and (.before | serving_identity)
  else false end)
)
