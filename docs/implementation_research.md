# Implementation research

Primary sources checked on 2026-08-27:

- [Qt for Python documentation](https://doc.qt.io/qtforpython-6/) identifies
  PySide6 as the official Qt 6 Python binding and publishes it under LGPLv3,
  GPLv3, or the Qt commercial license.
- [Qt for Python deployment](https://doc.qt.io/qtforpython-6/deployment/index.html)
  recommends `pyside6-deploy` for freezing desktop applications on Windows,
  macOS, and Linux. Native installers, signing, and notarization remain release
  engineering work after this Python-environment iteration.
- [Qt supported platforms](https://doc.qt.io/qtforpython-6/overviews/qtdoc-supported-platforms.html)
  confirms current desktop support for macOS and Windows; the project CI also
  includes Linux.
- [Official PRImA PAGE 2013 XSD](https://www.primaresearch.org/schema/PAGE/gts/pagecontent/2013-07-15/pagecontent.xsd)
  defines ordered TextLine `Coords`, optional connected-point `Baseline`, Words,
  and TextEquiv/Unicode. The downloaded upstream bytes had SHA-256
  `97ba8b0b5243d5f83076b9d166a2b622c91f1c0a6c382a5b83240de166407786`.
  The bundled copy only normalizes line endings and adds a final newline.
- [PRImA PAGE-XML repository](https://github.com/PRImA-Research-Lab/PAGE-XML)
  describes PAGE as an XSD-defined format for page regions, text lines, words,
  glyphs, reading order, and text content.

The official 2013 XSD confirms that `TranskribusMetadata` is not part of the
2013 Metadata sequence. Validation therefore reports strict validity separately
from an editable PAGE-core result produced from a temporary validation clone.
Only that known vendor metadata node is removed from the clone; source and saved
trees preserve it.
