SPHINXBUILD ?= python -m sphinx
SOURCEDIR = .
BUILDDIR = _build/sphinx

.PHONY: html clean

html:
	$(SPHINXBUILD) -b html "$(SOURCEDIR)" "$(BUILDDIR)"

clean:
	rm -rf _build
