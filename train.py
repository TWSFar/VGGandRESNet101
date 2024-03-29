import multiprocessing
multiprocessing.set_start_method('spawn', True)
import argparse
import visdom
import time
import random
import os
import os.path as osp
import val

from models import *
from data import *
from utils import *

import torch
import torch.optim as optim
import torch.optim.lr_scheduler as lr_scheduler
import torch.nn.functional as F
from torch.utils.data import DataLoader

hyp = {'lr0': 0.005,  # initial learning rate
       'lr_gamma': 0.1, # learning decay factory
       'lrf': -4.,  # final learning rate = lr0 * (10 ** lrf)
       'momentum': 0.90,  # SGD momentum
       'weight_decay': 0.0005}  # optimizer weight decay


def train(
        multi_scale = False,
        freeze_backbone = False,
        mode='train'):
    
    # config parameter
    device, gpu_num = torch_utils.select_device(is_head=True)
    start_epoch = 0
    cutoff = 10 # freeze backbone endpoint
    best = osp.join(opt.save_folder, opt.backbone + '_best.pt')
    latest = osp.join(opt.save_folder, opt.backbone + '_latest.pt')
    best_loss = float('inf')
    train_best_loss = float('inf')
    used_mulgpu = False

    #visualization
    if opt.visdom:
        vis = visdom.Visdom()
        vis_legend = ['correct', 'loss', 'F1']
        # epoch_plot = create_vis_plot(vis, 'Epoch', 'Loss', 'train loss', [vis_legend[0],])
        batch_plot = create_vis_plot(vis, 'Batch', 'Loss', 'batch loss', [vis_legend[0],])
        test_plot = create_vis_plot(vis, 'Epoch', 'Loss', 'test loss', vis_legend)

    # dataset load
    dataset = DogCat(opt.trainset_path, opt.img_size, mode)
    dataloader = DataLoader(
                            dataset,
                            batch_size=opt.batch_size,
                            num_workers=opt.num_workers,
                            shuffle=True,
                            pin_memory=True,
                            collate_fn=dataset.collate_fn
                            )

    # model and optimizer create , init, load checkpoint
    if opt.backbone == 'resnet':
        model = resnet101(pretrained = opt.pretrained)
    elif opt.backbone == 'vgg':
        model = vgg16(pretrained = opt.pretrained) 
    optimizer = optim.SGD(model.parameters(), lr=hyp['lr0'], momentum=hyp['momentum'], weight_decay=hyp['weight_decay'])
    scheduler = lr_scheduler.MultiStepLR(optimizer, milestones=[round(opt.epochs * x) for x in (0.8, 0.9)], gamma=hyp['lr_gamma']) 
    scheduler.last_epoch = start_epoch - 1
    
    # resume
    if opt.resume:
        try:
            model, best_loss, start_epoch, optimizer = resume_load_weights(model, optimizer, latest)
        except:
            print('load checkpoint failure, the file might be corrupted.\n Now, training from epoch 0...')
    # gpu set
    if opt.gpu > 1 and gpu_num > 1:
        device_id = []
        for i in range(min(opt.gpu, gpu_num)):
            device_id.append(i)
        model = torch.nn.DataParallel(model, device_ids=device_id)
        model.to(device) 
        used_mulgpu = True
    else:
        model.to(device)

    # Loss
    criterion = nn.CrossEntropyLoss().to(device)
    
    # train
    model.hyp = hyp
    model_info(model)
    batch_number = len(dataloader)
    n_burnin = min(round(batch_number / 5 + 1), 1000)  # burn-in batches
    total_time = time.time()
    for epoch in range(start_epoch, opt.epochs):
        print(('%10s' * 4) % ('Epoch', 'Batch', 'Loss', 'Time'))
        model.train()
        scheduler.step()
        
        # Freeze backbone at epoch 0, unfreeze at epoch 1 (optional)
        if freeze_backbone and epoch < 2:
            for name, p in model.named_parameters():
                if int(name.split('.')[1]) < cutoff: 
                    p.requires_grad = False if epoch == 0 else True

        for i, (imgs, label, file_) in enumerate(dataloader):
            imgs = imgs.to(device)
            label = label.to(device)
            start_time = time.time()

            # Multi-Scale training
            if multi_scale:
                if (i + 1 + batch_number * epoch) % 10 == 0:
                    img_size = random.choice(range(img_size_min, img_size_max + 1)) * 32
                    print('img_size = %g' % img_size)
                scale_factor = img_size / max(imgs.shape[-2:])
                imgs = F.interplot(imgs, scale_factor=scale_factor, mode='bilinear', align_corners=False)
            
            # SGD burn-in
            if epoch == 0 and i <= n_burnin:
                lr = hyp['lr0'] * (i / n_burnin) ** 4
                for x in optimizer.param_groups:
                    x['lr'] = lr
            
            # run model and compute loss
            pred = model(imgs)

            #loss = compute_loss(pred, loss)
            loss = criterion(pred, label[:, 1].view(-1))
            train_best_loss = min(train_best_loss, loss)
          
            if torch.isnan(loss):
                print('WARNING: nan loss detected, ending training')
                return results

            loss.backward()
            
            if (i + 1) % opt.accumulate == 0 or (i + 1) == batch_number:
                optimizer.step()
                optimizer.zero_grad()
            end_time = time.time()

            if opt.visdom:
                update_vis_plot(vis, batch_number*epoch+i, [loss.cpu()], batch_plot, 'append')
            
            summary = ('%8s%12s'+'%10.3g'*2) % (
                        '%g/%g' % (epoch, opt.epochs), 
                        '%g/%g' % (i, batch_number), 
                        loss, 
                        end_time-start_time)

            print(summary)
        
        if not opt.notest or epoch == opt.epochs - 1:
            with torch.no_grad():
                result = val.val(opt=opt, model=model, mode='test') # P, R, F1, test_loss
        
        if not osp.exists('result_log'):
            os.makedirs('result_log')
        with open(osp.join('result_log', opt.backbone + 'result.txt'), 'a') as file:
            file.write(summary + '%10.3g' * 3 % result + '\n') 

        test_loss = result[1]
        if test_loss < best_loss:
            best_loss = test_loss
        
        # visdom
        if opt.visdom:
            # update_vis_plot(vis, epoch, [train_best_loss], epoch_plot, 'append')
            update_vis_plot(vis, epoch, result, test_plot, 'append')
        
        save = (not opt.nosave) or (epoch == opt.epochs-1)
        if save:
            # Create checkpoint
            chkpt = {
                'epoch': epoch,
                'best_loss': best_loss,
                'model': model.module.state_dict() if used_mulgpu else model.state_dict(),
                'optimizer': None if used_mulgpu else optimizer.state_dict() 
            }
            if not osp.exists(opt.save_folder):
                os.makedirs(opt.save_folder)
            torch.save(chkpt, latest)
            if best_loss == test_loss:
                torch.save(chkpt, best)
            
            backup = False
            if backup and epoch > 0 and epoch % 10 ==0:
                torch.save(chkpt, osp(opt.save_folder, opt.backbone + 'backup_%g.pt' % epoch))
            # Delete checkpoint   
            del chkpt

    total_time = (time.time() - total_time) / 3600
    print("%g epochs completed in %.3f hours.%" % (epoch - start_epoch + 1, total_time))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='VGG training with Pytorch')
    parser.add_argument('--backbone', type=str, default='resnet', 
                        choices=['resnet', 'vgg'], help='backbone')
    parser.add_argument('--epochs', type=int, default=20, help='number of epochs')
    parser.add_argument('--batch-size', type=int, default=128, help='batch size')
    parser.add_argument('--cfg', type=str, default='cfg/vgg16.cfg', help='cfg file path')
    parser.add_argument('--single-scale', action='store_true', help='train at fixed size')
    parser.add_argument('--img-size', type=int, default=224, help='inference size')
    parser.add_argument('--resume', action='store_true', help='resume training flag')
    parser.add_argument('--nosave', action='store_true', help='do not save training results')
    parser.add_argument('--notest', action='store_true', help='only test final epoch')
    parser.add_argument('--evolve', action='store_true', help='run hyperparameter evolution')
    parser.add_argument('--number-classes', type=int, default=2, help='number of classes')
    parser.add_argument('--trainset_path', type=str, default='datasets/DogCat/train', help='train dataset path')
    parser.add_argument('--valset_path', type=str, default='datasets/DogCat/val', help='val dataset path')
    parser.add_argument('--save-folder', type=str, default='weights', help='Directory for saving checkpoint models')
    parser.add_argument('--accumulate', type=int, default=1, help='number of batches to accumulate before optimizing')
    parser.add_argument('--visdom', default=True, type=bool, help='Use visdom for loss visualization')
    parser.add_argument('--num-workers', type=int, default=4, help='number of Pytorch DataLoader workers')
    parser.add_argument('--pretrained', default=True, type=bool, help='use pre train')
    parser.add_argument('--gpu', default=4, type=int, help='number of gpu')
    opt=parser.parse_args()
    optdict = opt.__dict__
    for (key, value) in optdict.items():
        print(key, '=', value)
    print('')

    # opt.resume = True
    if opt.resume:
        opt.pretrained = False
    
    with open(osp.join('result_log', opt.backbone + 'result.txt'), 'a') as file:
            file.write(('\n%8s%12s'+'%11s'*2 + '%10s' * 3 + '\n') % ('epoch', 'batch_i', 'train_loss', 'time', 'correct', 'test_loss', 'f1'))
    train()