#!/usr/bin/python3 -I
"""Entry point for the vendored ClusterMAX: /usr/lib/clustermax/bin/cmax."""

import sys

sys.path.insert(0, "/usr/lib/clustermax/site")

from cmax.cli import main

sys.exit(main())
