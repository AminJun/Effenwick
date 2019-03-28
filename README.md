# Effenwick Pytorch
This project has been made based on the [wandering007](https://github.com/wandering007) work [efficient_densenet_pytorch](https://github.com/wandering007/efficient_densenet_pytorch), so to them we give all the credit. 

# efficient-densenet-pytorch

Memory-Efficient Implementation of DenseNets, supporting both **DenseNet and DeseNet-BC series**.

Environments: Linux CPU/GPU, Python 3, PyTorch 1.0

Check the implementation correctness by `python -m utils.gradient_checking.py` with different settings in `utils/gradient_checking.py` (CPU, single GPU, multiple GPUs).

Benchmark the forward/backward of efficient&non-efficient DenseNet by `python -m utils.benckmark_effi.py` (CPU, single GPU, multiple GPUs). The following results are reported on the Linux system equipped with 40 Intel(R) Xeon(R) CPUs (E5-2630 v4 @ 2.20GHz) and NVIDIA GTX TiTan 1080Ti.

Model setting:   
```python
num_init_features=24, block_config=(12, 12, 12), compression=1, input_size=32, bn_size=None, batch size=128.
```

|     Model     |           CPU           |          1 GPU          |         2 GPUs         |         4 GPUs         |
| :-----------: | :---------------------: | :---------------------: | :--------------------: | :--------------------: |
|   Efficient   | F=15849, B=36738, R=2.3 | F=38.0, B=103.5, R=2.72 | F=38.5, B=64.0, R=1.66 | F=63.3, B=77.5, R=1.23 |
| Non-efficient | F=24889, B=36732, R=1.5 | F=38.0, B=77.9, R=2.05  | F=36.2, B=42.1, R=1.16 | F=56.2, B=31.8, R=0.57 |

*F means average forward time (ms), B means average backward time (ms), R=B/F.*

The efficient version can process up to 1450 batches in a single GPU (~12GB), compared with 350 batches of the non-efficient version. That is, the efficient version is **~4x memory-efficient** as the non-efficient version.

## How to load the pretrained DenseNet into the efficient version?

*It is simple.*

Take DenseNet-121 as an example.

First, download [the checkpoint](https://github.com/pytorch/vision/blob/master/torchvision/models/densenet.py#L12):

```shell
wget https://download.pytorch.org/models/densenet121-a639ec97.pth
```

Then run

````shell
cd utils
python convert.py --to efficient --checkpoint densenet121-a639ec97.pth  --output densenet121_effi.pth
````

 Done.

You can load the state dict in the saved file `densenet121_effi.pth` into the efficient model now!

```python
import torch
from models import DenseNet
model = DenseNet(num_init_features=64, block_config=(6, 12, 24, 16), compression=0.5,
                 input_size=224, bn_size=4, num_classes=1000, efficient=True)
state_dict = torch.load('densenet121_effi.pth')
model.load_state_dict(state_dict, strict=True)
```

## Train efficient DenseNet on ImageNet

Easy configuration and run:

0. Install the requirements via `pip install -r requirements.txt`
1. Prepare ImageNet dataset following the [installation instructions](https://github.com/facebook/fb.resnet.torch/blob/master/INSTALL.md#download-the-imagenet-dataset), and the shell scripts in the `datasets/imagenet_pre` should be helpful.
2. Configure the experiment settings in `config.yaml`.
3. run the command like `./run.sh 0,1,2,3 config.yaml `.

You will find that 4 GPUs are totally enough for training the efficient model with batch size of `256`!

CIFAR training is also provided and easy to configure :-)

# References

Pleiss, Geoff, et al. "Memory-efficient implementation of densenets." *arXiv preprint arXiv:1707.06990* (2017).

