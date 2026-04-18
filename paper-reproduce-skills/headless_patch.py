"""Headless GUI mocks. Exec this before demo scripts that call cv2.imshow /
matplotlib.*.show() / open3d.visualization in a Docker container.

Usage:
    import runpy
    exec(open('/etc/headless_patches/headless_patch.py').read())
    runpy.run_path('demo.py', run_name='__main__')
"""

try:
    import cv2
    cv2.imshow = lambda *a, **kw: None
    cv2.waitKey = lambda *a, **kw: 0
    cv2.destroyAllWindows = lambda: None
    cv2.namedWindow = lambda *a, **kw: None
except ImportError:
    pass

try:
    import matplotlib
    matplotlib.use("Agg", force=True)
except ImportError:
    pass

try:
    import open3d as o3d
    if hasattr(o3d, "visualization"):
        o3d.visualization.draw_geometries = lambda *a, **kw: None
        if hasattr(o3d.visualization, "draw"):
            o3d.visualization.draw = lambda *a, **kw: None
except ImportError:
    pass
