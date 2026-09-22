"""What can be queued, and what each thing turns into on this board.

The dashboard renders its form from this registry, fetched from the device, so
the UI can never offer a job the daemon would not accept.
"""
import json
import os
import re

from . import paths as _paths


class ValidationError(Exception):
    pass


def load(path=None):
    path = path or os.path.join(_paths.bench_dir(), "job_kinds.json")
    with open(path) as f:
        return json.load(f)


def validate(registry, kind, params):
    spec = registry.get(kind)
    if spec is None:
        raise ValidationError("unknown job kind: %r (have: %s)"
                              % (kind, ", ".join(sorted(registry))))
    declared = spec["params"]
    unexpected = set(params) - set(declared)
    if unexpected:
        raise ValidationError("%s takes no parameter %s"
                              % (kind, ", ".join(sorted(unexpected))))

    out = {}
    for name, rule in declared.items():
        if name in params:
            value = params[name]
        elif "default" in rule:
            value = rule["default"]
        else:
            raise ValidationError("%s needs a %s" % (kind, name))

        if not isinstance(value, str):
            raise ValidationError("%s.%s must be a string" % (kind, name))
        if "enum" in rule and value not in rule["enum"]:
            raise ValidationError("%s.%s: %r is not one of %s"
                                  % (kind, name, value, ", ".join(rule["enum"])))
        if "pattern" in rule and not re.match(rule["pattern"], value):
            raise ValidationError("%s.%s: %r does not match %s"
                                  % (kind, name, value, rule["pattern"]))
        out[name] = value
    return out


def pick(mapping, params):
    """Resolve a {"param": {"value": result}} lookup against the job's params."""
    if mapping is None:
        return None
    if isinstance(mapping, str):
        return mapping
    (param, table), = mapping.items()
    return table.get(params.get(param))


def pick_memory(spec, params):
    """The MB this job kind needs for this model, or None if it declares none."""
    table = spec.get("memory_mb")
    if not table:
        return None
    return table.get(params.get("model"))


def pick_baseline(spec, params):
    """The baselines.json key this job must match, or None for an unchecked kind."""
    return pick(spec.get("baseline"), params)


def resolve(registry, kind, params, paths):
    spec = registry[kind]
    params = validate(registry, kind, params)

    label = spec["label"].format(**params)
    output_dir = spec["output_dir"].format(**params)
    # The suffix goes on BOTH. run_detail.py:42 matches a benchmark run to the
    # measured run that produced it by model plus a -(s\d)-\d{8} regex over the
    # measured directory name, which is built from the label. Leave the label
    # unsuffixed and a thinking-on and thinking-off run of the same model and
    # subset both land at mmlupro-e4b-s2-<stamp>; the lookup then returns
    # whichever is newer and silently attaches the wrong telemetry.
    suffix = pick(spec.get("suffix_when"), params)
    if suffix:
        label += suffix
        output_dir += suffix

    board = spec["boards"].get(paths.board)
    if board is None:
        raise ValidationError("%s cannot run on %s" % (kind, paths.board))

    fields = dict(params, label=label, output_dir=output_dir,
                  stdbench=paths.stdbench, measured=paths.measured)
    env = {k: v.format(**fields) for k, v in board.get("env", {}).items()}
    inner = board["command"].format(**fields)

    return {
        "label": label,
        "output_dir": output_dir,
        "command": "./run_measured.sh %s -- %s" % (label, inner),
        "env": env,
        "baseline": pick_baseline(spec, params),
        "memory_mb": pick_memory(spec, params),
        # The normalised params travel with the result so callers do not have
        # to validate a second time to learn what the defaults filled in.
        "params": params,
    }
