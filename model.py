import torch
import torch.nn as nn
import torch.nn.functional as F
from torchvision import models


class BaseModel(nn.Module):
    def __init__(self, num_classes, **kwargs):
        super().__init__()

        self.conv1 = nn.Conv2d(3, 32, kernel_size=7, stride=1)
        self.conv2 = nn.Conv2d(32, 64, kernel_size=3, stride=1)
        self.conv3 = nn.Conv2d(64, 128, kernel_size=3, stride=1)
        self.dropout1 = nn.Dropout(0.25)
        self.dropout2 = nn.Dropout(0.25)
        self.avgpool = nn.AdaptiveAvgPool2d((1, 1))
        self.fc = nn.Linear(128, num_classes)

    def forward(self, x):
        x = self.conv1(x)
        x = F.relu(x)

        x = self.conv2(x)
        x = F.relu(x)
        x = F.max_pool2d(x, 2)
        x = self.dropout1(x)

        x = self.conv3(x)
        x = F.relu(x)
        x = F.max_pool2d(x, 2)
        x = self.dropout2(x)

        x = self.avgpool(x)
        x = x.view(-1, 128)
        return self.fc(x)


# Pytorch Pretrained models
class PytorchModel(nn.Module):
    def __init__(self):
        super().__init__()

    def set_parameter_requires_grad(self, model, feature_extracting):
        if feature_extracting:
            for param in model.parameters():
                param.requires_grad = False


class Resnet18(PytorchModel):
    def __init__(self, num_classes, feature_extract=True, use_pretrained=True):
        super().__init__()
        self.num_classes = num_classes
        self.feature_extract = feature_extract
        self.use_pretrained = use_pretrained

        self.model_ft = models.resnet18(pretrained=self.use_pretrained)
        self.set_parameter_requires_grad(self.model_ft, self.feature_extract)
        num_ftrs = self.model_ft.fc.in_features
        self.model_ft.fc = nn.Linear(num_ftrs, self.num_classes)
        self.input_size = 224

    def forward(self, x):
        return self.model_ft(x)


class Resnet50(PytorchModel):
    def __init__(self, num_classes, feature_extract=True, use_pretrained=True):
        super().__init__()
        self.num_classes = num_classes
        self.feature_extract = feature_extract
        self.use_pretrained = use_pretrained

        self.model_ft = models.resnet50(pretrained=self.use_pretrained)
        self.set_parameter_requires_grad(self.model_ft, self.feature_extract)
        num_ftrs = self.model_ft.fc.in_features
        self.model_ft.fc = nn.Linear(num_ftrs, self.num_classes)
        self.input_size = 224

    def forward(self, x):
        return self.model_ft(x)


class Alexnet(PytorchModel):
    def __init__(self, num_classes, feature_extract=True, use_pretrained=True):
        super().__init__()
        self.num_classes = num_classes
        self.feature_extract = feature_extract
        self.use_pretrained = use_pretrained

        self.model_ft = models.alexnet(pretrained=self.use_pretrained)
        self.set_parameter_requires_grad(self.model_ft, self.feature_extract)
        num_ftrs = self.model_ft.classifier[6].in_features
        self.model_ft.classifier[6] = nn.Linear(num_ftrs, self.num_classes)
        self.input_size = 224

    def forward(self, x):
        return self.model_ft(x)


class VGG11bn(PytorchModel):
    def __init__(self, num_classes, feature_extract=True, use_pretrained=True):
        super().__init__()
        self.num_classes = num_classes
        self.feature_extract = feature_extract
        self.use_pretrained = use_pretrained

        self.model_ft = models.vgg11_bn(pretrained=self.use_pretrained)
        self.set_parameter_requires_grad(self.model_ft, self.feature_extract)
        num_ftrs = self.model_ft.classifier[6].in_features
        self.model_ft.classifier[6] = nn.Linear(num_ftrs, self.num_classes)
        self.input_size = 224

    def forward(self, x):
        return self.model_ft(x)


class Squeezenet(PytorchModel):
    def __init__(self, num_classes, feature_extract=True, use_pretrained=True):
        super().__init__()
        self.num_classes = num_classes
        self.feature_extract = feature_extract
        self.use_pretrained = use_pretrained

        self.model_ft = models.squeezenet1_0(pretrained=self.use_pretrained)
        self.set_parameter_requires_grad(self.model_ft, self.feature_extract)
        self.model_ft.classifier[1] = nn.Conv2d(
            512, num_classes, kernel_size=(1, 1), stride=(1, 1)
        )
        self.model_ft.num_classes = self.num_classes
        self.input_size = 224

    def forward(self, x):
        return self.model_ft(x)


class Densenet121(PytorchModel):
    def __init__(self, num_classes, feature_extract=True, use_pretrained=True):
        super().__init__()
        self.num_classes = num_classes
        self.feature_extract = feature_extract
        self.use_pretrained = use_pretrained

        self.model_ft = models.densenet121(pretrained=self.use_pretrained)
        self.set_parameter_requires_grad(self.model_ft, self.feature_extract)
        num_ftrs = self.model_ft.classifier.in_features
        self.model_ft.classifier = nn.Linear(num_ftrs, self.num_classes)
        self.input_size = 224

    def forward(self, x):
        return self.model_ft(x)


# Custom Model Template
class MyModel(nn.Module):
    def __init__(self, num_classes):
        super().__init__()

        """
        1. ?????? ?????? ???????????? parameter ??? num_claases ??? ??????????????????.
        2. ????????? ?????? ??????????????? ????????? ????????????.
        3. ????????? output_dimension ??? num_classes ??? ??????????????????.
        """

    def forward(self, x):
        """
        1. ????????? ????????? ?????? ??????????????? forward propagation ??? ??????????????????
        2. ????????? ?????? output ??? return ????????????
        """
        return x
