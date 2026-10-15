"""Check explicit product decisions without granting runtime or hardware acceptance."""


def validate_decisions(catalog):
    document = catalog.get('capability_decisions')
    if not isinstance(document, dict) or document.get('schema_version') != 1:
        return ['capability decisions missing or unsupported version']
    entries = document.get('behaviors')
    if not isinstance(entries, dict):
        return ['capability decisions must contain a behavior mapping']
    errors = []
    names = {n for row in catalog.get('routes', []) for n in row['executor_behaviors']}
    templates = set(catalog.get('behaviors', {}))
    presets = set(catalog.get('expression_presets', []))
    if not presets <= templates:
        errors.append('expression presets must have templates')
    # A legacy missing template or new preset must have a deliberate disposition.
    for name in (names - templates) | presets:
        if name not in entries:
            errors.append(f'{name}: missing capability decision')
    for name, entry in entries.items():
        if name not in names:
            errors.append(f'{name}: decision has no declared route')
        if not isinstance(entry, dict):
            errors.append(f'{name}: decision must be a mapping')
            continue
        decision = entry.get('decision')
        if decision == 'implemented_preset':
            if name not in presets or entry.get('completion_scope') != 'expression_only':
                errors.append(f'{name}: implemented decision must match an expression preset')
        elif decision == 'deferred_integration':
            if name in templates or entry.get('completion_scope') != 'unavailable':
                errors.append(f'{name}: stale deferred decision or invalid completion scope')
        else:
            errors.append(f'{name}: unsupported capability decision')
        if not isinstance(entry.get('reason'), str) or not entry['reason'].strip():
            errors.append(f'{name}: decision reason required')
        for key in ('owner_roles', 'required_evidence'):
            value = entry.get(key)
            if not isinstance(value, list) or not value or any(not isinstance(v, str) or not v.strip() for v in value):
                errors.append(f'{name}: nonempty {key} required')
    return errors
