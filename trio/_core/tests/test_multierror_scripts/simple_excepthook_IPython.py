import _common

# To tickle the "is IPython loaded?" logic, make sure that trio tolerates
# IPython loaded but not actually in use
import IPython

import simple_excepthook
