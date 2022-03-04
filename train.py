import argparse
import glob
import json
import multiprocessing
import os
import random
import re
from importlib import import_module
from pathlib import Path
from distutils import util

import matplotlib.pyplot as plt
import numpy as np
import torch
from torch.optim.lr_scheduler import StepLR
from torch.utils.data import DataLoader
from torch.utils.tensorboard import SummaryWriter
import torch.nn as nn
from sklearn.metrics import f1_score

from dataset import MaskBaseDataset
from loss import create_criterion



def seed_everything(seed):
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)  # if use multi-GPU
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    np.random.seed(seed)
    random.seed(seed)


def get_lr(optimizer):
    for param_group in optimizer.param_groups:
        return param_group['lr']


def grid_image(np_images, gts, preds, n=16, shuffle=False):
    batch_size = np_images.shape[0]
    assert n <= batch_size

    choices = random.choices(range(batch_size), k=n) if shuffle else list(range(n))
    figure = plt.figure(figsize=(12, 18 + 2))  # cautions: hardcoded, 이미지 크기에 따라 figsize 를 조정해야 할 수 있습니다. T.T
    plt.subplots_adjust(top=0.8)               # cautions: hardcoded, 이미지 크기에 따라 top 를 조정해야 할 수 있습니다. T.T
    n_grid = np.ceil(n ** 0.5)
    tasks = ["mask", "gender", "age"]
    for idx, choice in enumerate(choices):
        gt = gts[choice].item()
        pred = preds[choice].item()
        image = np_images[choice]
        # title = f"gt: {gt}, pred: {pred}"
        gt_decoded_labels = MaskBaseDataset.decode_multi_class(gt)
        pred_decoded_labels = MaskBaseDataset.decode_multi_class(pred)
        title = "\n".join([
            f"{task} - gt: {gt_label}, pred: {pred_label}"
            for gt_label, pred_label, task
            in zip(gt_decoded_labels, pred_decoded_labels, tasks)
        ])

        plt.subplot(n_grid, n_grid, idx + 1, title=title)
        plt.xticks([])
        plt.yticks([])
        plt.grid(False)
        plt.imshow(image, cmap=plt.cm.binary)

    return figure


def increment_path(path, exist_ok=False):
    """ Automatically increment path, i.e. runs/exp --> runs/exp0, runs/exp1 etc.

    Args:
        path (str or pathlib.Path): f"{model_dir}/{args.name}".
        exist_ok (bool): whether increment path (increment if False).
    """
    path = Path(path)
    if (path.exists() and exist_ok) or (not path.exists()):
        return str(path)
    else:
        dirs = glob.glob(f"{path}*")
        matches = [re.search(rf"%s(\d+)" % path.stem, d) for d in dirs]
        i = [int(m.groups()[0]) for m in matches if m]
        n = max(i) + 1 if i else 1
        return f"{path}{n}"


def train(k, data_dir, model_dir, args):
    seed_everything(args.seed)
    tasks = ["mask", "gender", "age"]

    save_dir = increment_path(os.path.join(model_dir, 'k'+str(k), args.name))

    # -- settings
    use_cuda = torch.cuda.is_available()
    device = torch.device("cuda" if use_cuda else "cpu")

    # -- dataset
    dataset_module = getattr(import_module("dataset"), args.dataset)  # default: MaskBaseDataset
    dataset = dataset_module(
        data_dir=data_dir,
        kfold = args.kfold,
        k=args.k,
        age_parameter=args.data_selection
    )
    # task별로 모델 만들 때 num_classes 구하기
    if args.multi_label == 'mask' or args.multi_label == 'age':
        num_classes = 3
    elif args.multi_label == 'gender':
        num_classes = 2
    else:
        num_classes = 18

    # -- augmentation
    transform_module = getattr(import_module("dataset"), args.augmentation)  # default: BaseAugmentation
    transform = transform_module(
        resize=args.resize,
        mean=dataset.mean,
        std=dataset.std,
    )
    dataset.set_transform(transform)

    # -- data_loader
    print(dataset.split_dataset())
    train_set, val_set = dataset.split_dataset()

    train_loader = DataLoader(
        train_set,
        batch_size=args.batch_size,
        num_workers=multiprocessing.cpu_count()//2,
        shuffle=True,
        pin_memory=use_cuda,
        drop_last=True,
    )

    val_loader = DataLoader(
        val_set,
        batch_size=args.valid_batch_size,
        num_workers=multiprocessing.cpu_count()//2,
        shuffle=False,
        pin_memory=use_cuda,
        drop_last=False,
    )

    # -- model
    model_module = getattr(import_module("model"), args.model)  # default: BaseModel
    model = model_module(
        num_classes=num_classes,
        feature_extract=args.feature_extract,
        use_pretrained=args.pretrained
    ).to(device)


    model = torch.nn.DataParallel(model)

    # -- loss & metric
    def multi_criterion(loss_func, outputs, pictures):
        # multi label classification model
        losses = 0
        # print(pictures)
        losses += 0.4 * loss_func(outputs['age'], pictures['age'].to(device))
        losses += 0.3 * loss_func(outputs['gender'], pictures['gender'].to(device))
        losses += 0.3 * loss_func(outputs['mask'], pictures['mask'].to(device))
        return losses

    if args.criterion == 'multi_label':
        # multi label classification
        loss_func = create_criterion('cross_entropy')
    else:
        criterion = create_criterion(args.criterion)  # default: cross_entropy
    opt_module = getattr(import_module("torch.optim"), args.optimizer)  # default: SGD
    optimizer = opt_module(
        model.parameters(), # 레이어 프리즈하다 프리즈 풀고 트레이닝 하기 위해 수정
        lr=args.lr,
        weight_decay=args.weight_decay
    )
    # None if LR scheduler is not in use
    scheduler = None

    # -- logging
    logger = SummaryWriter(log_dir=save_dir)
    with open(os.path.join(save_dir, 'config.json'), 'w', encoding='utf-8') as f:
        json.dump(vars(args), f, ensure_ascii=False, indent=4)

    best_val_acc = 0
    best_val_loss = np.inf
    best_f1_score = 0

    data_mix = getattr(import_module("dataset"), args.data_mix)

    for epoch in range(args.epochs):
        # model parameter freeze 풀기
        if epoch == 2:
            for param in model.parameters():
                param.requires_grad = True
        # train loop
        model.train()
        loss_value = 0
        matches = 0
        for idx, train_batch in enumerate(train_loader):
            inputs, labels = train_batch
            preds = {}
            if not args.criterion == 'multi_label':
                # task별로 모델 따로 사용할 때 label
                if args.multi_label == 'mask':
                    labels = labels['mask']
                elif args.multi_label == 'age':
                    labels = labels['age']
                elif args.multi_label == 'gender':
                    labels = labels['gender']

            optimizer.zero_grad()
        
            if not args.mixp == 0.:
                # mixup, cutmix
                if np.random.random() < args.mixp:
                    inputs, lam, target_a, target_b = data_mix(inputs, labels, device)
                    outs = model(inputs)
                    loss = criterion(outs, target_a) * lam + criterion(outs, target_b) * (1.-lam)
                else :
                    inputs = inputs.to(device)
                    labels = labels.to(device)
                    outs = model(inputs)
                    loss = criterion(outs, labels)
            else:
                inputs = inputs.to(device)
                outs = model(inputs)
                if not args.criterion == 'multi_label':
                    labels = labels.to(device)
            
            if args.criterion =='multi_label':
                # multi label classification 사용 시 task별로 따로 분류
                for task in tasks:
                    preds[task] = torch.argmax(outs[task], dim=-1)
                loss = multi_criterion(loss_func, outs, labels)
            else:
                preds = torch.argmax(outs, dim=-1)

            
            preds = MaskBaseDataset.encode_multi_class(preds['mask'],preds['gender'],preds['age'])
            loss.backward()
            optimizer.step()

            loss_value += loss.item()
            if args.criterion =='multi_label':
                matches += (preds.cpu() == labels['label'].cpu()).sum().item()

            if (idx + 1) % args.log_interval == 0:
                train_loss = loss_value / args.log_interval
                train_acc = matches / args.batch_size / args.log_interval
                current_lr = get_lr(optimizer)
                print(
                    f"Epoch[{epoch}/{args.epochs}]({idx + 1}/{len(train_loader)}) || "
                    f"training loss {train_loss:4.4} || training accuracy {train_acc:4.2%} || lr {current_lr}"
                )
                logger.add_scalar("Train/loss", train_loss, epoch * len(train_loader) + idx)
                logger.add_scalar("Train/accuracy", train_acc, epoch * len(train_loader) + idx)

                loss_value = 0
                matches = 0
        if scheduler:
            scheduler.step()

        # val loop
        with torch.no_grad():
            print("Calculating validation results...")
            model.eval()
            val_loss_items = []
            val_acc_items = []
            target_tensor = []
            pred_tensor = []
            figure = None
            for val_batch in val_loader:
                inputs, labels = val_batch
                preds = {}
                if not args.criterion == 'multi_label':
                    # task별로 모델 따로 사용할 때 label
                    if args.multi_label == 'mask':
                        labels = labels['mask']
                    elif args.multi_label == 'age':
                        labels = labels['age']
                    elif args.multi_label == 'gender':
                        labels = labels['gender']
                    labels = labels.to(device)
                inputs = inputs.to(device)

                outs = model(inputs)

                if args.criterion =='multi_label':
                    for task in tasks:
                        preds[task] = torch.argmax(outs[task], dim=-1)
                    loss = multi_criterion(loss_func, outs, labels)
                    preds = MaskBaseDataset.encode_multi_class(preds['mask'],preds['gender'],preds['age'])
                    acc_item = (labels['label'].cpu() == preds.cpu()).sum().item()
                    loss_item = loss.item()
                    target_tensor.append(labels['label'].cpu())
                    # losses.append(loss.item())
                else:
                    loss = criterion(outs, labels)
                    preds = torch.argmax(outs, dim=-1)
                    loss_item = criterion(outs, labels).item()
                    acc_item = (labels == preds).sum().item()
                    target_tensor.append(labels.cpu())

                loss_item = criterion(outs, labels).item()
                acc_item = (labels == preds).sum().item()
                val_loss_items.append(loss_item)
                val_acc_items.append(acc_item)

                pred_tensor.append(preds.cpu())
                target_tensor.append(labels.cpu())

                if figure is None:
                    inputs_np = torch.clone(inputs).detach().cpu().permute(0, 2, 3, 1).numpy()
                    inputs_np = dataset_module.denormalize_image(inputs_np, dataset.mean, dataset.std)
                    figure = grid_image(
                        inputs_np, labels, preds, n=16, shuffle=args.dataset != "MaskSplitByProfileDataset"
                    )

            val_f1 = f1_score(torch.cat(target_tensor), torch.cat(pred_tensor), average='macro')
            val_loss = np.sum(val_loss_items) / len(val_loader)
            val_acc = np.sum(val_acc_items) / len(val_set)
            best_val_acc = max(best_val_acc, val_acc)
            best_val_loss = min(best_val_loss, val_loss)

            if val_f1 > best_f1_score:
                print(f"New best model for val f1 : {val_f1:4.2%}! saving the best model..")
                torch.save(model.module.state_dict(), f"{save_dir}/best.pth")
                best_f1_score = val_f1
            torch.save(model.module.state_dict(), f"{save_dir}/last.pth")
            print(
                f"[Val] acc : {val_acc:4.2%}, loss: {val_loss:4.2}, F1: {val_f1:4.4} || "
                f"best acc : {best_val_acc:4.2%}, best loss: {best_val_loss:4.2}"
            )

            logger.add_scalar("Val/loss", val_loss, epoch)
            logger.add_scalar("Val/accuracy", val_acc, epoch)
            logger.add_scalar("Val/F1", val_f1, epoch)
            logger.add_figure("results", figure, epoch)
            print()


if __name__ == '__main__':
    torch.cuda.empty_cache()

    parser = argparse.ArgumentParser()

    from dotenv import load_dotenv
    import os
    load_dotenv(verbose=True)

    # Data and model checkpoints directories
    parser.add_argument('--seed', type=int, default=42, help='random seed (default: 42)')
    parser.add_argument('--epochs', type=int, default=1, help='number of epochs to train (default: 1)')
    parser.add_argument('--dataset', type=str, default='MaskBaseDataset', help='dataset augmentation type (default: MaskBaseDataset)')
    parser.add_argument('--augmentation', type=str, default='BaseAugmentation', help='data augmentation type (default: BaseAugmentation)')
    parser.add_argument('--dataset_mean', type=tuple, default=(0.485, 0.456, 0.406), help='default: imagenet data: (0.485, 0.456, 0.406). mask dataset data: (0.548, 0.504, 0.479)')
    parser.add_argument('--dataset_std', type=tuple, default=(0.229, 0.224, 0.225), help='default: imagenet data: (0.229, 0.224, 0.225). mask dataset data: (0.237, 0.247, 0.246)')
    parser.add_argument("--resize", nargs="+", type=list, default=[224, 224], help='resize size for image when training')
    parser.add_argument('--batch_size', type=int, default=64, help='input batch size for training (default: 64)')
    parser.add_argument('--valid_batch_size', type=int, default=256, help='input batch size for validing (default: 256)')
    parser.add_argument('--model', type=str, default='BaseModel', help='model type (default: BaseModel)')
    parser.add_argument('--optimizer', type=str, default='Adam', help='optimizer type (default: Adam)')
    parser.add_argument('--lr', type=float, default=1e-4, help='learning rate (default: 1e-4)')
    parser.add_argument('--weight_decay', type=float, default=0, help='weight decay (defalut: 0)')
    parser.add_argument('--val_ratio', type=float, default=0.2, help='ratio for validaton (default: 0.2)')
    parser.add_argument('--criterion', type=str, default='cross_entropy', help='criterion type (default: cross_entropy)')
    parser.add_argument('--lr_decay_step', type=int, default=1000, help='learning rate scheduler deacy step (default: 1000)')
    parser.add_argument('--log_interval', type=int, default=20, help='how many batches to wait before logging training status')
    parser.add_argument('--name', default='exp', help='model save at {SM_MODEL_DIR}/{name}')
    parser.add_argument('--pretrained', type=lambda x: bool(util.strtobool(x)), default=True, help='use torchvision pretrained model')
    parser.add_argument('--feature_extract', type=lambda x: bool(util.strtobool(x)), default=False, help='freeze parameters of pretrained model except fc layer')
    parser.add_argument('--multi_label', type=str, default="multi_label", help='multi label (default: mask)')
    parser.add_argument('--data_mix', type=str, default="mixup", help='mixup or cutmix batch (default : mixup)')
    parser.add_argument('--mixp', type=float, default=0., help='cutmix probability (default : 0.5)')
    parser.add_argument('--kfold', type=int, default=5, help='set kfold num (default:5)')
    parser.add_argument('--k', type=int, default=0, help='set kfold num (default:0)')
    parser.add_argument('--images', type=str, default='train/images', help='images or fdimages')
    parser.add_argument('--data_selection', type=str, default='1_0_0', help="How to use a data; 'real images'_'threshold of old fake images'_'threshold of young fake images'")
    parser.add_argument('--wrong_image', type=lambda x: bool(util.strtobool(x)), default=False)


    # Container environment
    args = parser.parse_args()

    parser.add_argument('--data_dir', type=str, default=os.environ.get('SM_CHANNEL_TRAIN', '/opt/ml/input/data/' + args.images))
    parser.add_argument('--model_dir', type=str, default=os.environ.get('SM_MODEL_DIR', './model'))

    args = parser.parse_args()
    print(args)

    data_dir = args.data_dir
    model_dir = args.model_dir

    
    train(args.k, data_dir, model_dir, args)
