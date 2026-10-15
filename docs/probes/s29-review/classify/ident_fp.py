import sys
sys.path.insert(0, "/home/burhan/auspex-new")
from auspex.classify.classifier import classify
from auspex.classify import shortcut_answer
qs = [
 # security questions about makers/vendors/models
 "who made the Emotet malware?", "who made emotet?", "what model of firewall is this?",
 "which company created Cobalt Strike?", "who created this chat?", "who created this chat",
 "who is behind this bot?", "who's behind this bot", "who owns this bot?", "who owns this platform?",
 "who built this platform?", "who developed this bot?", "who made this bot?",
 "which company is behind this bot?", "what company is behind this bot?",
 "which provider do you use?", "what provider do you use?", "which vendor do you use?",
 "what engine do you use?", "what model do you use?", "which ai made this?", "what llm made this?",
 "which ai wrote this?", "what ai did this?", "which model did this?", "what ai is behind this?",
 "which ai is this?", "what engine is this?", "what model is this?", "what model is this",
 "is this gemini?", "is this gemini", "is this chatgpt?", "is this claude?", "is this llama?",
 "is this grok?", "is this mistral?", "is this deepseek?", "is this qwen?",
 "is this gpt?", "is this gpt-4o?", "is this glm?", "is this copilot?",
 "is this powered by google?", "is this built on meta?", "is this made by google?",
 "is this thing deepseek or something else?",
 "are you from google?", "did google make you?", "did meta build u",
 "what are you running on?", "what are you built on?", "what's under the hood?",
 "what is under the hood?", "what's under the hood", "whats under the hood",
 "who is this", "who is this?", "what are you", "what are you?",
 # analyst follow-ups that point at a work object via "this ..."
 "who created this chat in teams?", "what ai is this phishing kit using?",
 "which ai is behind this campaign?", "who made this platform vulnerable?",
 "what's the model?", "what's your model?", "what is your engine",
 "what ai model is this?", "what language model is this?", "which llm is this?",
 "which llm is this", "what model version is this?",
 "what's the engine behind this?", "what's the ai behind this?",
 "what is the model behind this?", "what's the provider behind this?",
 "which model is behind this?", "which model trained this?",
 "what's the llm behind this?", "what kind of ai is this?", "what kind of model is this?",
 "which engine powers this?", "what model powers this?", "what engine powers this?",
 "what ai powers this?", "what llm powers this?",
 "so what model is this?", "ok what engine is this?",
 "what model is me", "what ai are me",
 "is this mistral or something else?", "is this llama2?",
 "are you meta?", "r u google", "are you copilot?", "are you from meta or google",
 "are you a gemini or something", "are you google or not",
]
for q in qs:
    c = classify(q)
    a = shortcut_answer(c)
    print(f"{c.category.value:10s} {q}")
