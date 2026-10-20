"""CSV + explicit plan -> bounded slit fit, baseline and finite acquisition choices."""
from photonguard.experiments.reuse_cli import main
from photonguard.experiments.inverse_models import SLIT

if __name__ == '__main__':
    main(SLIT)
