def env(self, cmd, data):
    if cmd == RETRO_ENVIRONMENT_SET_VARIABLES:
        ptr = ctypes.cast(data, POINTER(RetroVariable))
        i = 0
        if self.trace_core_vars:
            print('[corevar] SET_VARIABLES begin', flush=True)
        while ptr[i].key:
            key = decode_cstr(ptr[i].key)
            raw = decode_cstr(ptr[i].value)
            default = None
            if ';' in raw:
                default = raw.split(';', 1)[1].strip().split('|', 1)[0].strip()
                if default:
                    self.variables[key] = default.encode('utf-8')
            if key in self.core_option_overrides:
                self.variables[key] = self.core_option_overrides[key]
            if self.trace_core_vars:
                selected = self.variables.get(key)
                selected_text = selected.decode('utf-8', errors='replace') if selected is not None else '<none>'
                override = key in self.core_option_overrides
                if override or key.startswith('dolphin_'):
                    print(f'[corevar] register key={key} default={default!r} selected={selected_text!r} override={override}', flush=True)
            i += 1
        if self.trace_core_vars:
            for k, v in sorted(self.core_option_overrides.items()):
                vv = v.decode('utf-8', errors='replace')
                present = k in self.variables
                print(f'[corevar] override-summary key={k} value={vv!r} registered={present}', flush=True)
            print('[corevar] SET_VARIABLES end', flush=True)
        return True
    if cmd == RETRO_ENVIRONMENT_GET_VARIABLE:
        if not data:
            return True
        var_ptr = ctypes.cast(data, POINTER(RetroVariable))
        key = decode_cstr(var_ptr[0].key)
        if key in self.core_option_overrides:
            val = self.core_option_overrides[key]
            source = 'override'
        else:
            val = self.variables.get(key)
            source = 'default/cache'
        if self.trace_core_vars:
            value_text = val.decode('utf-8', errors='replace') if val is not None else '<null>'
            print(f'[corevar] GET key={key} value={value_text!r} source={source}', flush=True)
        if val is not None:
            var_ptr[0].value = val
        else:
            var_ptr[0].value = None
        return True
