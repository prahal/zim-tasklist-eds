install:
	sudo cp ./tasklist-eds.py "$(shell dirname $(shell /usr/bin/env python -c 'import zim;print zim.__file__'))/plugins"
