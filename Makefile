.PHONY: bootstrap check syntax deploy verify

bootstrap:
	./scripts/bootstrap.sh

check:
	.venv/bin/python scripts/static_check.py
	bash -n scripts/bootstrap.sh

syntax:
	.venv/bin/ansible-playbook --syntax-check site.yml --ask-vault-pass

deploy:
	.venv/bin/ansible-playbook site.yml --ask-vault-pass

verify:
	.venv/bin/ansible-playbook scripts/verify.yml --ask-vault-pass
