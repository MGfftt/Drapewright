import yaml, sys
cfg = yaml.safe_load(open('assets/design_params/design_used.yaml', encoding='utf-8'))
paths = sys.argv[1:]
def get(cfg, path):
    node = cfg
    for k in path.split('.'):
        if not isinstance(node, dict) or k not in node:
            return None
        node = node[k]
    return node
for p in paths:
    node = get(cfg, p)
    if node is None:
        print('%-42s MISSING' % p); continue
    t = node.get('type')
    extra = ''
    if 'range' in node:
        extra += ' range=%s' % (node['range'],)
    if t == 'select':
        extra += ' options=%s' % (node.get('options') or node.get('range'),)
    if 'default_prob' in node:
        extra += ' p=%s' % node['default_prob']
    print('%-42s type=%-8s v=%-6s%s' % (p, t, node.get('v'), extra))
