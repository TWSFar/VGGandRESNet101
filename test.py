import argparse
from tqdm import tqdm

from utils import *
from models import *
from data import *

import torch
from torch.utils.data import DataLoader


def test(
    opt,
    img_size = 224,
    model=None,
    mode='test',
    classes=['Cat', 'Dog']):
    
    # Configure
    device = torch_utils.select_device()
    best = osp.join(opt.save_folder, 'best.pt')
    latest = osp.join(opt.save_folder, 'latest.pt')

    # model
    if model is None:
        model = VGG(opt.cfg, img_size).to(device)
        model.load_state_dict(torch.load(best)['model'])    

    # Loss
    criterion = nn.CrossEntropyLoss().to(device)
    
    # dataset
    dataset = DogCat(opt.testset_path, img_size, mode)\
    
    dataloader = DataLoader(dataset,
                            batch_size=opt.batch_size,
                            num_workers=4,
                            pin_memory=True,
                            collate_fn=dataset.collate_fn)

    # test
    model.eval()
    loss, p, r, f1 = 0, 0, 0, 0
    total = 0
    corrects = 0
    stats = []
    for batch_i, (imgs, labels, file_) in enumerate(tqdm(dataloader, desc='Computing Loss')):
        labels = labels.to(device)
        imgs = imgs.to(device)
        labels = labels[:, 1].view(-1)
        # Run model
        output = model(imgs)

        # Compute Loss
        loss_i = criterion(output, labels)
        loss = loss + loss_i.item()


        _, predicted = output.max(1)
        corrects += predicted.eq(labels).sum().item()
        
        labels = labels.tolist()
        total += len(labels)
        
        for x, y in zip(predicted.tolist(), labels):
            stats.append((x, y))

    
    stats = np.array(stats).astype(np.int64)
    num_per_class = np.bincount(stats[:, 1], minlength=opt.number_classes)

    corrects = 1. * corrects / total
    if len(stats):
        p, r, f1 = res_per_class(stats, total, opt.number_classes)
        mp, mr, mf1 = p.mean(), r.mean(), f1.mean()    
    
    print(('%10s' * 6) % ('Class_num', 'Labels', 'P', 'R', 'F1', 'loss'))
    print(("%10d"+"%10.3g"*5) % (opt.number_classes, total, corrects, mr, mf1, loss))

    if opt.number_classes > 1 and len(stats):
        for i, c in enumerate(classes):
            print(("%10s"+"%10d" + "%10.3g"*3) % (c, num_per_class[i], p[i], r[i], f1[i]))
    print()

    return corrects, loss 


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog='test.py')
    parser.add_argument('--cfg', type=str, default='cfg/vgg16.cfg', help='cfg file path')
    parser.add_argument('--batch-size', type=int, default=16, help='batch size')
    parser.add_argument('--img-size', type=int, default=224, help='inference size (pixels)')
    parser.add_argument('--number-classes', type=int, default=2, help='number of classes')
    parser.add_argument('--testset-path', type=str, default='datasets/DogCat/test', help='path of dataset')
    parser.add_argument('--save-folder', type=str, default='weights', help='Directory for saving checkpoint models')
    opt = parser.parse_args()
    
    with torch.no_grad():
        result = test(opt, mode='test')
