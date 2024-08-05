import sys

for module in list(sys.modules.keys()):
    if module.startswith("trio"):
        del sys.modules[module]
