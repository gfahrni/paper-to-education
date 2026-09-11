# pdf-to-education — raccourcis du pipeline.
# `make` seul affiche l'aide. Variables surchargeables, ex. `make pptx VOICE=fr_male`.

PAPER ?= paper-processed
OUT   ?= llm-output
TTS   ?= mlx

ifeq ($(TTS),say)
VOICE ?= Thomas
else
VOICE ?= fr_female
endif
SPEED ?= 1.0

TTS_URL    ?= http://127.0.0.1:8000/v1/audio/speech
TTS_LANG   ?= fr
TTS_CONFIG ?= tts.json

.PHONY: help install extract storyboard pptx serve-tts

help:
	@echo "make install     : crée .venv et installe les dépendances Python"
	@echo "make extract     : PDF -> $(PAPER)/ (extract.py)"
	@echo "make storyboard  : $(PAPER)/ -> $(OUT)/ storyboard + voiceover (LLM)"
	@echo "make pptx        : $(OUT)/ -> presentation.pptx + voiceover ($(TTS), voix $(VOICE), $(SPEED)x, avance auto)"
	@echo "make serve-tts   : démarre le serveur TTS local (mlx_audio.server sur :8000)"
	@echo ""
	@echo "Variables : PAPER=$(PAPER) OUT=$(OUT) TTS=$(TTS) VOICE=$(VOICE) SPEED=$(SPEED)"
	@echo "            TTS_URL=$(TTS_URL) TTS_LANG=$(TTS_LANG) TTS_CONFIG=$(TTS_CONFIG)"

install:
	python3 -m venv .venv
	.venv/bin/python -m pip install --upgrade pip
	.venv/bin/python -m pip install -r requirements.txt
	@echo "Environnement prêt. Active-le : source .venv/bin/activate"

extract:
	python extract.py --out $(PAPER)

storyboard:
	python llm-process.py --paper $(PAPER) --out $(OUT)

pptx:
	python build_pptx.py --in $(OUT) --audio --tts $(TTS) \
		--tts-config $(TTS_CONFIG) --tts-url $(TTS_URL) --tts-lang $(TTS_LANG) \
		--voice $(VOICE) --speed $(SPEED) --advance --serve-tts

serve-tts:
	mlx_audio.server --host 127.0.0.1 --port 8000
