import torch
import torch.nn as nn
import torch.nn.functional as F
from efficient_utils import _EfficientDensenetBottleneck, _SharedAllocation
from functools import reduce
from operator import mul


class _DenseLayer(nn.Module):
    def __init__(self, shared_alloc, num_input_features, growth_rate, bn_size, drop_rate, input_size):
        super(_DenseLayer, self).__init__()
        if bn_size:
            if shared_alloc is not None:
                self.add_module('bottleneck', _EfficientDensenetBottleneck(
                    shared_alloc=shared_alloc, num_input_channels=num_input_features,
                    num_output_channels=bn_size * growth_rate,
                    kernel_size=1, bias=False))
            else:
                self.add_module('norm1', nn.BatchNorm2d(num_input_features))
                self.add_module('relu1', nn.ReLU())
                self.add_module('conv1', nn.Conv2d(num_input_features, bn_size *
                                                   growth_rate, kernel_size=1, stride=1, bias=False))
            self.add_module('norm2', nn.BatchNorm2d(bn_size * growth_rate))
            self.add_module('relu2', nn.ReLU())
            self.add_module('conv2', nn.Conv2d(bn_size * growth_rate, growth_rate,
                                               kernel_size=3, stride=1, padding=1, bias=False))
        else:
            if shared_alloc is not None:
                self.add_module('bottleneck', _EfficientDensenetBottleneck(
                    shared_alloc=shared_alloc, num_input_channels=num_input_features,
                    num_output_channels=growth_rate,
                    kernel_size=3, stride=1, padding=1, bias=False))
            else:
                self.add_module('norm1', nn.BatchNorm2d(num_input_features))
                self.add_module('relu1', nn.ReLU())
                self.add_module('conv1', nn.Conv2d(num_input_features, growth_rate,
                                                   kernel_size=3, stride=1, padding=1, bias=False))
        self.drop_rate = drop_rate
        self.params = sum([param.numel() for param in self.parameters()])
        self.flops = self.params * input_size ** 2

    def forward(self, x):
        if hasattr(self, 'bottleneck'):
            x = self.bottleneck(x)
        else:
            x = self._modules['norm1'](x)
            x = self._modules['relu1'](x)
            x = self._modules['conv1'](x)
        if hasattr(self, 'norm2'):
            x = self._modules['norm2'](x)
            x = self._modules['relu2'](x)
            x = self._modules['conv2'](x)

        if self.drop_rate > 0:
            x = F.dropout(x, p=self.drop_rate, training=self.training)
        return x


class _Transition(nn.Sequential):
    def __init__(self, num_input_features, num_output_features):
        super(_Transition, self).__init__()
        self.add_module('norm', nn.BatchNorm2d(num_input_features))
        self.add_module('relu', nn.ReLU())
        self.add_module('conv', nn.Conv2d(num_input_features, num_output_features,
                                          kernel_size=1, stride=1, bias=False))
        self.add_module('pool', nn.AvgPool2d(kernel_size=2, stride=2))


class _DenseBlock(nn.Module):
    def __init__(self, num_layers, num_input_features, bn_size, growth_rate, drop_rate,
                 input_size, shared_alloc=None):
        super(_DenseBlock, self).__init__()
        self.growth_rate = growth_rate
        self.shared_alloc = shared_alloc
        if shared_alloc is not None:
            self.final_num_features = num_input_features + growth_rate * num_layers
        for i in range(num_layers):
            layer = _DenseLayer(shared_alloc=self.shared_alloc,
                                num_input_features=num_input_features + i * growth_rate,
                                growth_rate=growth_rate, bn_size=bn_size,
                                drop_rate=drop_rate,
                                input_size=input_size)
            self.add_module('denselayer%d' % (i + 1), layer)

    def forward(self, x):
        if self.shared_alloc is not None:
            # Update storage type
            self.shared_alloc[0].type_as(x)
            self.shared_alloc[1].type_as(x)
            # Resize storage
            final_size = list(x.size())
            final_size[1] = self.final_num_features
            final_storage_size = reduce(mul, final_size, 1)
            self.shared_alloc[0].resize_(final_storage_size)
            self.shared_alloc[1].resize_(final_storage_size)
            outputs = [x]
            for module in self.children():  # already in the right order
                new_features = module(outputs)
                outputs.append(new_features)
            outputs = torch.cat(outputs, dim=1)

        else:
            outputs = x
            for module in self.children():
                new_features = module(outputs)
                outputs = torch.cat([outputs, new_features], dim=1)
        return outputs


class DenseNet(nn.Module):
    def __init__(self, in_channels=3, num_init_features=24, block_config=(12, 12, 12), compression=1,
                 input_size=32, bn_size=None, drop_rate=0, num_classes=100, efficient=False):

        super(DenseNet, self).__init__()
        assert 0 < compression <= 1, 'compression of densenet should be between 0 and 1'
        growth_rate = num_init_features // 2
        self.features = nn.Sequential()
        # first conv
        if input_size > 32:
            self.features.add_module('conv0', nn.Conv2d(in_channels, num_init_features,
                                                        kernel_size=7, stride=2, padding=3, bias=False))
            input_size //= 2
            flops = in_channels * num_init_features * 49 * input_size * input_size
            self.features.add_module('norm0', nn.BatchNorm2d(num_init_features))
            self.features.add_module('relu0', nn.ReLU())
            self.features.add_module('pool0', nn.MaxPool2d(kernel_size=3, stride=2, padding=1))
            input_size //= 2
        else:
            self.features.add_module('conv0', nn.Conv2d(in_channels, num_init_features,
                                                        kernel_size=3, stride=1, padding=1, bias=False))
            flops = in_channels * num_init_features * 9 * input_size * input_size
        # Each denseblock
        num_features = num_init_features
        shared_alloc = (_SharedAllocation(), _SharedAllocation()) if efficient else None
        current_layer_pos = 0
        for i, num_layers in enumerate(block_config):
            block = _DenseBlock(num_layers=num_layers,
                                num_input_features=num_features,
                                bn_size=bn_size, growth_rate=growth_rate,
                                drop_rate=drop_rate, input_size=input_size,
                                shared_alloc=shared_alloc)
            current_layer_pos += num_layers
            self.features.add_module('denseblock%d' % (i + 1), block)
            for m in block.children():
                flops += m.flops

            num_features += num_layers * growth_rate
            if i == len(block_config) - 1:
                break
            out_features = int(num_features * compression)
            trans = _Transition(num_input_features=num_features,
                                num_output_features=out_features)
            self.features.add_module('transition%d' % (i + 1), trans)
            flops += input_size * input_size * num_features * out_features
            num_features = out_features
            input_size //= 2
        # Final batch norm
        self.features.add_module('norm%d' % (len(block_config) + 1), nn.BatchNorm2d(num_features))

        # Linear layer
        self.classifier = nn.Linear(num_features, num_classes)

        # Official init from torch repo.
        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                nn.init.kaiming_normal_(m.weight)
            elif isinstance(m, nn.BatchNorm2d):
                nn.init.constant_(m.weight, 1)
                nn.init.constant_(m.bias, 0)
            elif isinstance(m, nn.Linear):
                nn.init.constant_(m.bias, 0)
            elif isinstance(m, _EfficientDensenetBottleneck):
                nn.init.constant_(m._parameters['norm_weight'], 1)
                nn.init.constant_(m._parameters['norm_bias'], 0)
                nn.init.kaiming_normal_(m._parameters['conv_weight'])

        self.flops = flops
        self.num_params = sum([param.numel() for param in self.parameters()])

    def forward(self, x):
        features = self.features(x)
        out = F.relu(features)
        out = F.avg_pool2d(out, kernel_size=out.size(2)).view(out.size(0), -1)
        out = F.dropout(out, p=0.5, training=self.training)
        out = self.classifier(out)
        return out
