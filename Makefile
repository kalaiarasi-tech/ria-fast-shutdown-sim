.PHONY: demo clean

VENV := .venv
PY := $(VENV)/bin/python

demo: $(VENV)
	$(PY) -m pip install -U pip
	$(PY) -m pip install -e .
	ria-sim --outdir ./out

$(VENV):
	python3 -m venv $(VENV)
	. $(VENV)/bin/activate

clean:
	rm -rf $(VENV) out out_ci dist build *.egg-info
