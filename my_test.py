# -*- coding: utf-8 -*-
"""
Created on Wed Oct 26 15:09:57 2022

@author: ScanImage
"""

import sys, os, argparse, glob, pathlib, time
import subprocess

import numpy as np
from natsort import natsorted
from tqdm import tqdm
import utils, models, core, my_io
import matplotlib.pyplot as plt
import logging

# settings re-grouped a bit
def main():
    parser = argparse.ArgumentParser(description='cellpose parameters')

    # settings for CPU vs GPU
    hardware_args = parser.add_argument_group("hardware arguments")
    hardware_args.add_argument('--use_gpu', action='store_true', default=True, help='use gpu if torch with cuda installed')
    hardware_args.add_argument('--gpu_device', required=False, default=0, type=int, help='which gpu device to use')
    hardware_args.add_argument('--check_mkl', action='store_true', help='check if mkl working')
        
    # settings for locating and formatting images
    input_img_args = parser.add_argument_group("input image arguments")
    input_img_args.add_argument('--dir',
                        default=[], type=str, help='folder containing data to run or train on.')
    input_img_args.add_argument('--image_path',
                        default=[r'C:\Users\ScanImage\CellCounting\New folder\1\Ch A\23-dsd harvest 3_A_01_RAW_GFP.tif'], type=str, help='if given and --dir not given, run on single image instead of folder (cannot train with this option)')
    input_img_args.add_argument('--RFP_path',
                        default=[r'C:\Users\ScanImage\CellCounting\New folder\1\Ch A\23-dsd harvest 3_A_01_RAW_RFP.tif'], type=str, help='if given and --dir not given, run on single image instead of folder (cannot train with this option)')
    input_img_args.add_argument('--GFP_path',
                        default=[r'C:\Users\ScanImage\CellCounting\New folder\1\Ch A\23-dsd harvest 3_A_01_RAW_GFP.tif'], type=str, help='if given and --dir not given, run on single image instead of folder (cannot train with this option)')
    input_img_args.add_argument('--luna_path',
                        default=[r'C:\Users\ScanImage\CellCounting\New folder\1\Ch A\23-dsd harvest 3_A_01_TAG_ALL.tif'], type=str, help='if given and --dir not given, run on single image instead of folder (cannot train with this option)')
    
    input_img_args.add_argument('--look_one_level_down', action='store_true', help='run processing on all subdirectories of current folder')
    input_img_args.add_argument('--img_filter',
                        default=[], type=str, help='end string for images to run on')
    input_img_args.add_argument('--channel_axis',
                        default=None, type=int, help='axis of image which corresponds to image channels')
    input_img_args.add_argument('--z_axis',
                        default=None, type=int, help='axis of image which corresponds to Z dimension')
    input_img_args.add_argument('--chan',
                        default=0, type=int, help='channel to segment; 0: GRAY, 1: RED, 2: GREEN, 3: BLUE. Default: %(default)s')
    input_img_args.add_argument('--chan2',
                        default=0, type=int, help='nuclear channel (if cyto, optional); 0: NONE, 1: RED, 2: GREEN, 3: BLUE. Default: %(default)s')
    input_img_args.add_argument('--invert', action='store_true', help='invert grayscale channel')
    input_img_args.add_argument('--all_channels', action='store_true', help='use all channels in image if using own model and images with special channels')
    
    # model settings 
    model_args = parser.add_argument_group("model arguments")
    model_args.add_argument('--pretrained_model', required=False, default='cyto', type=str, help='model to use for running or starting training')
    model_args.add_argument('--add_model', required=False, default=None, type=str, help='model path to copy model to hidden .cellpose folder for using in GUI/CLI')
    model_args.add_argument('--unet', action='store_true', help='run standard unet instead of cellpose flow output')
    model_args.add_argument('--nclasses',default=3, type=int, help='if running unet, choose 2 or 3; cellpose always uses 3')

    # algorithm settings
    algorithm_args = parser.add_argument_group("algorithm arguments")
    algorithm_args.add_argument('--no_resample', action='store_true', help="disable dynamics on full image (makes algorithm faster for images with large diameters)")
    algorithm_args.add_argument('--net_avg', action='store_true', help='run 4 networks instead of 1 and average results')
    algorithm_args.add_argument('--no_interp', action='store_true', help='do not interpolate when running dynamics (was default)')
    algorithm_args.add_argument('--no_norm', action='store_true', help='do not normalize images (normalize=False)')
    algorithm_args.add_argument('--do_3D', action='store_true', help='process images as 3D stacks of images (nplanes x nchan x Ly x Lx')
    algorithm_args.add_argument('--diameter', required=False, default=8., type=float, 
                        help='cell diameter, if 0 will use the diameter of the training labels used in the model, or with built-in model will estimate diameter for each image')
    algorithm_args.add_argument('--stitch_threshold', required=False, default=0.0, type=float, help='compute masks in 2D then stitch together masks with IoU>0.9 across planes')
    algorithm_args.add_argument('--fast_mode', action='store_true', help='now equivalent to --no_resample; make code run faster by turning off resampling')
    
    algorithm_args.add_argument('--flow_threshold', default=0.0, type=float, help='flow error threshold, 0 turns off this optional QC step. Default: %(default)s')
    algorithm_args.add_argument('--cellprob_threshold', default=-0.3, type=float, help='cellprob threshold, default is 0, decrease to find more and larger masks')
    
    algorithm_args.add_argument('--anisotropy', required=False, default=1.0, type=float,
                        help='anisotropy of volume in 3D')
    algorithm_args.add_argument('--exclude_on_edges', action='store_true', help='discard masks which touch edges of image')
    
    # output settings
    output_args = parser.add_argument_group("output arguments")
    output_args.add_argument('--save_png', action='store_true', help='save masks as png and outlines as text file for ImageJ')
    output_args.add_argument('--save_tif', action='store_true', default=1, help='save masks as tif and outlines as text file for ImageJ')
    output_args.add_argument('--no_npy', action='store_true', help='suppress saving of npy')
    output_args.add_argument('--savedir',
                        default=None, type=str, help='folder to which segmentation results will be saved (defaults to input image directory)')
    output_args.add_argument('--dir_above', action='store_true', help='save output folders adjacent to image folder instead of inside it (off by default)')
    output_args.add_argument('--in_folders', action='store_true', help='flag to save output in folders (off by default)')
    output_args.add_argument('--save_flows', action='store_true', help='whether or not to save RGB images of flows when masks are saved (disabled by default)')
    output_args.add_argument('--save_outlines', action='store_true', help='whether or not to save RGB outline images when masks are saved (disabled by default)')
    output_args.add_argument('--save_ncolor', action='store_true', help='whether or not to save minimal "n-color" masks (disabled by default')
    output_args.add_argument('--save_txt', action='store_true', help='flag to enable txt outlines for ImageJ (disabled by default)')

    # misc settings
    parser.add_argument('--verbose', action='store_true', default=True, help='show information about running and settings and save to log')
    
    args = parser.parse_args()

    if args.check_mkl:
        mkl_enabled = models.check_mkl()
    else:
        mkl_enabled = True
    
    if args.verbose:
        from my_io import logger_setup
        logger, log_file = logger_setup()
    else:
        print('>>>> !NEW LOGGING SETUP! To see cellpose progress, set --verbose')
        print('No --verbose => no progress or info printed')
        logger = logging.getLogger(__name__)

    channels = [args.chan, args.chan2]

    # find images
    if len(args.img_filter)>0:
        imf = args.img_filter
    else:
        imf = None


    # Check with user if they REALLY mean to run without saving anything 
    saving_something = args.save_png or args.save_tif or args.save_flows or args.save_ncolor or args.save_txt
                
    device, gpu = models.assign_device(use_torch=True, gpu=args.use_gpu, device=args.gpu_device)

    if args.pretrained_model is None or args.pretrained_model == 'None' or args.pretrained_model == 'False' or args.pretrained_model == '0':
        pretrained_model = False
    else:
        pretrained_model = args.pretrained_model
    
    model_type = None
    if pretrained_model and not os.path.exists(pretrained_model):
        model_type = pretrained_model if pretrained_model is not None else 'cyto'
        model_strings = models.get_user_models()
        all_models = models.MODEL_NAMES.copy() 
        all_models.extend(model_strings)
        if ~np.any([model_type == s for s in all_models]):
            model_type = 'cyto'
            logger.warning('pretrained model has incorrect path')

        if model_type=='nuclei':
            szmean = 17. 
        else:
            szmean = 15.
    builtin_size = model_type == 'cyto' or model_type == 'cyto2' or model_type == 'nuclei'


    tic = time.time()
    if len(args.dir) > 0:
        image_names = my_io.get_image_files(args.dir, 
                                        args.mask_filter, 
                                        imf=imf,
                                        look_one_level_down=args.look_one_level_down)
    else:
        if os.path.exists(args.image_path[0]):
            image_names = args.image_path
        else:
            raise ValueError(f'ERROR: no file found at {args.image_path}')
    nimg = len(image_names)
        
    cstr0 = ['GRAY', 'RED', 'GREEN', 'BLUE']
    cstr1 = ['NONE', 'RED', 'GREEN', 'BLUE']
    logger.info('>>>> running cellpose on %d images using chan_to_seg %s and chan (opt) %s'%
                    (nimg, cstr0[channels[0]], cstr1[channels[1]]))
     
    # handle built-in model exceptions; bacterial ones get no size model 
    if builtin_size:
        model = models.Cellpose(gpu=gpu, device=device, model_type=model_type, 
                                        net_avg=(not args.fast_mode or args.net_avg))
        
    else:
        if args.all_channels:
            channels = None  
        pretrained_model = None if model_type is not None else pretrained_model
        model = models.CellposeModel(gpu=gpu, device=device, 
                                     pretrained_model=pretrained_model,
                                     model_type=model_type,
                                     net_avg=False)
    
    # handle diameters
    if args.diameter==0:
        if builtin_size:
            diameter = None
            logger.info('>>>> estimating diameter for each image')
        else:
            logger.info('>>>> not using cyto, cyto2, or nuclei model, cannot auto-estimate diameter')
            diameter = model.diam_labels
            logger.info('>>>> using diameter %0.3f for all images'%diameter)
    else:
        diameter = args.diameter
        logger.info('>>>> using diameter %0.3f for all images'%diameter)
    
    
    tqdm_out = utils.TqdmToLogger(logger,level=logging.INFO)
    
    for image_name in tqdm(image_names, file=tqdm_out):
        image = my_io.imread(image_name)
        print('image shape: ',image.shape)
        out = model.eval(image, channels=channels, diameter=diameter,
                        do_3D=args.do_3D, net_avg=(not args.fast_mode or args.net_avg),
                        augment=False,
                        resample=(not args.no_resample and not args.fast_mode),
                        flow_threshold=args.flow_threshold,
                        cellprob_threshold=args.cellprob_threshold,
                        stitch_threshold=args.stitch_threshold,
                        invert=args.invert,
                        min_size=100,
                        # batch_size=args.batch_size,
                        interp=(not args.no_interp),
                        normalize=(not args.no_norm),
                        channel_axis=args.channel_axis,
                        z_axis=args.z_axis,
                        anisotropy=args.anisotropy,
                        model_loaded=True)
        masks, flows = out[:2]
        if len(out) > 3:
            diams = out[-1]
        else:
            diams = diameter
        if args.exclude_on_edges:
            masks = utils.remove_edge_masks(masks)
        if not args.no_npy:
            my_io.masks_flows_to_seg(image, masks, flows, diams, image_name, channels)
        if saving_something:
            my_io.save_masks(image, masks, flows, image_name, png=args.save_png, tif=args.save_tif,
                          save_flows=args.save_flows,save_outlines=args.save_outlines,
                          save_ncolor=args.save_ncolor,dir_above=args.dir_above,savedir=args.savedir,
                          save_txt=args.save_txt,in_folders=args.in_folders)
        live,dead = utils.split_live_dead_cells(masks, args.RFP_path, args.GFP_path, RThreshold=40, GThreshold=12)
        utils.plot_results_with_input(live, dead, image, args.luna_path)
    logger.info('>>>> completed in %0.3f sec'%(time.time()-tic))
  
if __name__ == '__main__':
    main()
    
