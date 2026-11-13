# Third-Party Asset Notice

`industrial_workshop_foundry_2k.hdr` is the Industrial Workshop Foundry HDRI by Poly Haven.

- Source: https://polyhaven.com/a/industrial_workshop_foundry
- License: CC0 1.0 Universal
- Download checksum (MD5): `b32ccf18584d284cead88d36ec617c8c`

The HDRI is used only as an environment-lighting and reflection source. The factory geometry, robot, route, inspection images, observations, and mission results remain locally generated synthetic demo content.

`industrial-workshop-hero.svg` is the `/overview` hero photograph: a tonemapped derivative of the same HDRI (Reinhard tonemapping, resized to 1920 px wide), embedded as a base64 JPEG inside an SVG wrapper because this repository is pushed through a text-only snapshot tool. Same CC0 1.0 terms as the source HDRI. To regenerate: decode the RLE RGBE HDRI, Reinhard-tonemap with gamma 2.2, save as JPEG, and base64-embed it in the SVG.
