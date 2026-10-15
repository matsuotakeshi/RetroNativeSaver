"""Legacy core option selection and diagnostics, without C pointers or callbacks."""

def register_variable(key, raw, variables, overrides, trace):
    default = None
    if ";" in raw:
        default = raw.split(";", 1)[1].strip().split("|", 1)[0].strip()
        if default:
            variables[key] = default.encode("utf-8")

    if key in overrides:
        variables[key] = overrides[key]

    if trace:
        selected = variables.get(key)
        selected_text = (
            selected.decode("utf-8", errors="replace")
            if selected is not None else "<none>"
        )
        override = key in overrides
        if override or key.startswith("dolphin_"):
            print(
                f"[corevar] register key={key} "
                f"default={default!r} selected={selected_text!r} "
                f"override={override}",
                flush=True,
            )


def lookup_variable(key, variables, overrides, trace):
    # Overrides must also work for options that the core queries
    # dynamically without first exposing them via SET_VARIABLES.
    if key in overrides:
        val = overrides[key]
        source = "override"
    else:
        val = variables.get(key)
        source = "default/cache"

    if trace:
        value_text = (
            val.decode("utf-8", errors="replace")
            if val is not None else "<null>"
        )
        print(
            f"[corevar] GET key={key} "
            f"value={value_text!r} source={source}",
            flush=True,
        )
    return val
