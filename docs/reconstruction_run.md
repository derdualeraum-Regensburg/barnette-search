# Completed reconstruction run

The reconstruction completed successfully on 2026-09-18. The local run
directory is `results/reconstruction-20260917/`; it is ignored by Git. Its final
status records 65 completed stages and no active controller.

## Completed work

1. Regenerate the complete census certificates at orders 26 through 36,
   then orders 8 through 25, to obtain one consistent new package. Odd orders
   are excluded by parity. Each nonempty order is checked by the existing
   independent standard-library verifier before proceeding.
2. Verify the assembled extremal sequence through order 36. For larger orders,
   this means upper certificates for every graph and exact certificates for
   all potential maximizers, not an exact hsep value for every graph.
3. Construct D(9,9), D(11,9), and D(11,11) at orders 40, 44, and 48 and generate
   new graph-specific exact certificates with independent verification.

The existing solvers and verifiers are unchanged. The driver uses the generic
exact-order producer for order 36 because the historical import source is lost.
The two-worker limit applies to the census. The larger double ladders run
serially. All three parts completed and passed their independent verification
stages.

These are newly computed certificates with new runtime metadata and hashes.
They do not recover the historical files byte for byte or recreate the lost
prediction-lock timestamp. Galleries and the separate symbolic packing/primal
lift analysis packages are not included in this computational queue.
The driver itself does not publish anything. The compact final data, excluding
working checkpoints, is prepared separately as the v0.9.0 release asset.

## Manual control

From PowerShell, in the prepared directory (the CMD launchers enable script
execution only for their own PowerShell process; system settings stay unchanged):

```powershell
.\start.cmd
```

This starts a hidden process at below-normal priority using the prepared source
snapshot, with standard output and errors in that directory. Read its status:

```powershell
Get-Content .\work\status.json
.\status.cmd
```

Request a pause:

```powershell
.\pause.cmd
```

The pause command waits for the controller to terminate its calculation subprocesses
and record `paused`. Each start keeps separate timestamped controller logs.
Completed per-graph checkpoints remain; the graph interrupted mid-calculation
may need to restart. To continue:

```powershell
.\resume.cmd
```

Wait until the previous controller has exited before resuming. After a failed
stage, inspect `work/logs/` before retrying. Failed double-ladder attempts are
retained in separate numbered directories. Configuration and program hashes
must match on resume. The PC must remain on and awake for calculations to make
progress; this preparation does not change Windows power settings.

## Checks and completion

Before the instruction not to start further calculations, small smoke checks
successfully regenerated and independently verified the cube and D(3,3), with
exact hsep 12 for the latter. They are separate from the prepared full run.
The full run was authorized and completed on 2026-09-18. Its state is recorded
in `work/status.json`; use `status.cmd` to also check whether the controller is alive.
The launch scripts verify the frozen preparation hashes before every start.
After a PC restart, use `resume.ps1` manually. A large double-ladder attempt
interrupted during optimization restarts that graph in a new attempt directory;
there is no checkpoint inside the optimizer.
