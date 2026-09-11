# pdf-to-education — raccourcis du pipeline.
# `make` seul affiche l'aide. Variables surchargeables, ex. `make pptx VOICE=Alice`.

PAPER ?= paper-processed
OUT   ?= llm-output
VOICE ?= George
SPEED ?= 1.25

.PHONY: help extract storyboard pptx preview

help:
	@echo "make extract     : PDF -> $(PAPER)/ (extract.py)"
	@echo "make storyboard  : $(PAPER)/ -> $(OUT)/ storyboard + voiceover (LLM)"
	@echo "make pptx        : $(OUT)/ -> presentation.pptx + voiceover ElevenLabs (voix $(VOICE), $(SPEED)x, avance auto)"
	@echo "make preview     : écoute un échantillon de la voix $(VOICE)"
	@echo ""
	@echo "Variables : PAPER=$(PAPER) OUT=$(OUT) VOICE=$(VOICE) SPEED=$(SPEED)"

extract:
	python extract.py --out $(PAPER)

storyboard:
	python llm-process.py --paper $(PAPER) --out $(OUT)

pptx:
	python build_pptx.py --in $(OUT) --audio --tts elevenlabs --voice $(VOICE) --speed $(SPEED) --advance

preview:
	python build_pptx.py --tts elevenlabs --voice $(VOICE) --speed $(SPEED) --preview
