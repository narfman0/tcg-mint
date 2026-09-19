"""The workbench: a local web interface over the library (`mint serve`).

It reads the workspace -- sets, the art cache with every variant, the render
manifests -- and drives it: renders, enhances and restyles run as jobs on one
worker thread (ComfyUI and Chromium are both serial anyway), and edits go
through the set schema back into the set file, which stays hand-editable.
"""
