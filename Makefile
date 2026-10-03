# pdf-to-education — raccourcis du pipeline.
# `make` seul affiche l'aide. Variables surchargeables, ex. `make pptx VOICE=fr_male`.

PAPER ?= paper-processed
OUT   ?= llm-output
MODE  ?= journal
DEPTH ?= summary
KIND  ?= auto
RENDER_DPI ?= 150
TTS   ?= mlx

ifeq ($(TTS),say)
VOICE ?= Thomas
else
VOICE ?= fr_female
endif
SPEED ?= 1.0
ADVANCE ?= 1

TTS_URL    ?= http://127.0.0.1:8000/v1/audio/speech
TTS_LANG   ?= fr
TTS_CONFIG ?= tts.json

.PHONY: help install extract storyboard course pptx serve-tts

help:
	@echo "Pipeline :"
	@echo "  make install     : crée .venv et installe les dépendances Python"
	@echo "  make extract     : PDF/dossier -> $(PAPER)/ (extract.py)"
	@echo "  make storyboard  : $(PAPER)/ -> $(OUT)/ storyboard + voiceover (LLM)"
	@echo "  make pptx        : $(OUT)/ -> presentation.pptx + voiceover ($(TTS), voix $(VOICE), $(SPEED)x)"
	@echo "  make serve-tts   : démarre le serveur TTS local (mlx_audio.server sur :8000)"
	@echo ""
	@echo "Choix de rendu :"
	@echo "  MODE=journal|course        registre (défaut : journal)"
	@echo "  DEPTH=summary|extensive    profondeur (défaut : summary)"
	@echo "  KIND=auto|article|non_article   type de doc (défaut : auto)"
	@echo "  ex. make storyboard MODE=course DEPTH=extensive"
	@echo "  ex. make course      : raccourci MODE=course"
	@echo ""
	@echo "Variables : PAPER=$(PAPER) OUT=$(OUT) MODE=$(MODE) DEPTH=$(DEPTH) KIND=$(KIND) TTS=$(TTS)"
	@echo "            VOICE=$(VOICE) SPEED=$(SPEED) ADVANCE=$(ADVANCE) RENDER_DPI=$(RENDER_DPI)"
	@echo "            ADVANCE=0 : pas d'avance auto (clic pour changer de slide)"

install:
	python3 -m venv .venv
	.venv/bin/python -m pip install --upgrade pip
	.venv/bin/python -m pip install -r requirements.txt
	@echo "Environnement prêt. Active-le : source .venv/bin/activate"

extract:
	python extract.py --out $(PAPER) --kind $(KIND) --render-dpi $(RENDER_DPI)

storyboard:
	python llm-process.py --paper $(PAPER) --out $(OUT) \
		--mode $(MODE) --depth $(DEPTH)

# Raccourci : cours (dossier de PDF). Ex. make course DEPTH=extensive
course:
	$(MAKE) storyboard MODE=course

pptx:
	python build_pptx.py --in $(OUT) --audio --tts $(TTS) \
		--tts-config $(TTS_CONFIG) --tts-url $(TTS_URL) --tts-lang $(TTS_LANG) \
		--voice $(VOICE) --speed $(SPEED) \
		$(if $(filter 1,$(ADVANCE)),--advance,) --serve-tts

serve-tts:
	mlx_audio.server --host 127.0.0.1 --port 8000
