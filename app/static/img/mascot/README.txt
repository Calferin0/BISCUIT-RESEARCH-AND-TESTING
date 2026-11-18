Tony, the BRT mascot. These files stay on the BRT PC (git-ignored; the repo is public).

  tony.png          cut-out, 640 px tall: home-page hero, empty state, his file page
  tony-96.png       top-bar logo
  tony-favicon.png  browser-tab icon
  tony.glb          3D scan for /tony: geometry + base-colour texture only, 1024 px

Rebuild them from CF's originals in ..\..\..\..\assets\ (Tony.png, Tony.glb) with:
  py -3.14 -I tools\make_mascot.py assets app\static\img\mascot
(needs Pillow; it's a one-off tool, not an app dependency).

If tony.png is missing, BRT falls back to the cookie emoji and /tony returns 404.
If tony.glb is missing, /tony shows the photo only.
