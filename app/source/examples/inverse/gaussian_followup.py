"""Plan five declared z positions, then separately approve the joint radius fit."""
from photonguard.experiments.reuse_cli import main
from photonguard.experiments.inverse_models import GAUSSIAN

if __name__ == '__main__':
    main(GAUSSIAN)
