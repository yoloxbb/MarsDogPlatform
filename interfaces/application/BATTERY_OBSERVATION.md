# Battery observation in behavior-result metadata, version 1

This is an application JSON contract on the existing result metadata, not a BMS,
embedded or docking protocol. No hardware producer is implemented or activated.

```json
{
  "battery_observation": {
    "schema_version": 1,
    "percentage": 88,
    "observed_at": 1790595100.0,
    "source": "deployment-owned-battery-reader",
    "simulated": false
  }
}
```

The example timestamp is illustrative and must not be replayed as live evidence.

## Consumer rules

Needs validates observations when consuming ACTION_RECHARGE results (COMPLETED,
INTERRUPTED/CANCELLED or TIMEOUT), or through ExecuteRecharge(metadata)/Recharge(metadata).
A result status alone never changes Energy. Other actions keep their existing rules.

- schema_version must be the integer 1 (not true); simulated must be the boolean false.
- percentage must be a finite JSON number in [0,100], not a boolean or numeric string.
- observed_at is UTC Unix wall-clock seconds, a finite number. Age at consumption
  must be 0..5 seconds inclusive; future and stale timestamps are rejected. The
  bound is a conservative application default pending measured telemetry cadence;
  it is not a claim about any existing hardware rate. Clocks must be synchronized.
- source must be a nonempty string identifying the deployment-owned reader.
  This is provenance, not authentication; trusted publishers are a deployment
  requirement. Merely adding these fields does not verify a sensor.
- If legacy energyValue/energy_value/batteryValue is also present, it must be a
  numeric non-boolean value equal to percentage; conflicts are rejected. Legacy
  scalar fields alone are insufficient, including through an older BT mapper.
- Existing integer conversion is retained: battery is int(percentage), Energy
  demand is 100 - battery. Invalid values are rejected, never clamped or defaulted.
- Missing/invalid observations leave the current Energy state and drain remainder
  unchanged. No observation is synthesized from an action result or configuration.
- Existing event-ID deduplication remains: rejected events also consume their ID.
  A later valid observation requires a new event ID. This is event deduplication,
  not a persistent per-sensor sample ledger.

charging_completed=false does not invalidate an independently valid battery
observation: measured state may update even when charging/docking has not completed.
Conversely, charging_completed=true is not evidence of battery percentage. This
contract does not define a docking-completion signal or authorize physical movement.

## Module responsibilities and compatibility

Action currently emits energy_settlement=observation_unavailable for successful
restInPlace/recharge and emits neither fabricated energyValue nor charging_completed.
recharge_result_energy_value remains declared for old launch-file compatibility,
but is ignored as battery evidence. _read_battery_level returns None. No Lite3
battery field or Go2 status is implicitly promoted into a measured observation.

BT forwards metadata and does not fill, repair or clamp electric state. Needs is
the enforcement point, including direct Recharge calls. Startup initialization,
explicit SetEnergyBatteryValue and simulation/time-drain APIs are unchanged; these
are not evidence-driven behavior-result settlement and must not be mistaken for
live battery telemetry.

No ROS IDL, topic, launch default or dependency pin changes. This is an intentional
behavioral compatibility break approved by the user: old scalar-only producers no
longer settle Energy in new Needs. Deploy matching Action/BT/Needs together. An old
Needs consumer can still manufacture full charge from missing metadata; never use
that mixed profile for production. Future telemetry readers must be independently
verified for units, timestamps, simulation identity and actual source deployment.
