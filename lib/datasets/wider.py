# --------------------------------------------------------
# SSH: Single Stage Headless Face Detector
# Wider Dataset Loader
# Written by Pouya Samangouei
# --------------------------------------------------------
from __future__ import print_function
import cPickle
import csv
import os
import subprocess

import numpy as np
import scipy.sparse
from PIL import Image

from utils.get_config import cfg
from datasets.imdb import imdb

class wider(imdb):
    def __init__(self, split, wider_path=None):
        self._test_flag = False
        self._split = split
        imdb.__init__(self, 'wider_' + split)
        self._image_set = split
        if wider_path is None:
            self._dataset_path = self._get_default_path()
        else:
            self._dataset_path = wider_path
        self._imgs_path = os.path.join(self._dataset_path, 'WIDER_{}'.format(split), 'images')
        csv_path = os.path.join(self._dataset_path, 'WIDER_{}'.format(split), 'imglist.csv')

        if not os.path.exists(csv_path) and split != 'test':
            path = os.path.join(os.path.dirname(__file__),
                                '..', 'wider_eval_tools')
            cmd = 'cd {} && '.format(path)
            cmd += 'matlab -nodisplay -nodesktop '
            cmd += '-r "dbstop if error; '
            cmd += 'wider_write_csv(\'{:s}\',\'{:s}\',\'{:s}\'); quit;"' \
                .format(self._dataset_path, split,
                        csv_path)
            print('Running:\n{}'.format(cmd))
            status = subprocess.call(cmd, shell=True)
        elif split == 'test':
            self._test_flag = True

        self._fp_bbox_map = {}
        with open(csv_path, 'r') as f:
            reader = csv.reader(f)
            if not self._test_flag:
                for row in reader:
                    if not row[0] in self._fp_bbox_map.keys():
                        self._fp_bbox_map[row[0]] = []
                    x1 = max(0, int(row[1]))
                    y1 = max(0, int(row[2]))
                    w = int(row[3])
                    h = int(row[4])
                    self._fp_bbox_map[row[0]].append([x1, y1,
                                                      x1 + w,
                                                      y1 + h])
                self._image_paths = self._fp_bbox_map.keys()
            else:
                self._image_paths = []
                for row in reader:
                    self._image_paths.append(row[0])

        self._image_index = range(len(self._image_paths))
        self._classes = ['_bg', 'face']

    def _get_default_path(self):
        return os.path.join(cfg.DATA_DIR,'datasets', 'wider')

    def image_path_at(self, i):
        return self.image_path_from_index(self._image_index[i])

    def image_path_from_index(self, index):
        image_path = os.path.join(self._imgs_path, self._image_paths[index])
        assert os.path.exists(image_path), \
            'Path does not exist: {}'.format(image_path)
        return image_path

    def gt_roidb(self):
        cache_file = os.path.join(self.cache_path, '{}_{}_gt_roidb.pkl'.format(self.name, self._split))
        if os.path.exists(cache_file):
            with open(cache_file, 'rb') as fid:
                roidb = cPickle.load(fid)
            print('{} gt roidb loaded from {}'.format(self.name, cache_file))
            return roidb

        roidb = []

        for fp in self._image_paths:
            if self._test_flag:
                roidb.append({'image_size': Image.open(os.path.join(self._imgs_path, fp)).size,
                              'file_path': os.path.join(self._imgs_path, fp)})
            else:
                boxes = np.zeros([len(self._fp_bbox_map[fp]), 4], np.float)

                gt_classes = np.ones([len(self._fp_bbox_map[fp])], np.int32)
                overlaps = np.zeros([len(self._fp_bbox_map[fp]), 2], np.float)

                ix = 0

                for bbox in self._fp_bbox_map[fp]:
                    imsize = Image.open(os.path.join(self._imgs_path, fp)).size

                    x1 = bbox[0]
                    y1 = bbox[1]
                    x2 = min(imsize[0], bbox[2])
                    y2 = min(imsize[1], bbox[3])

                    if (x2 - x1) < 1 or y2 - y1 < 1:
                        continue

                    boxes[ix, :] = np.array([x1, y1, x2, y2], np.float)

                    cls = int(1)
                    gt_classes[ix] = cls
                    overlaps[ix, cls] = 1.0
                    ix += 1
                overlaps = scipy.sparse.csr_matrix(overlaps)

                roidb.append({'boxes': boxes,
                              'gt_classes': gt_classes,
                              'gt_overlaps': overlaps,
                              'flipped': False,
                              'blurred': False,
                              'image_size': imsize,
                              'file_path': os.path.join(self._imgs_path, fp)})

        with open(cache_file, 'wb') as fid:
            cPickle.dump(roidb, fid, cPickle.HIGHEST_PROTOCOL)
        print('wrote gt roidb to {}'.format(cache_file))

        return roidb

    def write_detections(self, all_boxes, output_dir='./output/'):

        print('Writing the detections to text files: {}...'.format( output_dir), end='')
        for i in range(len(self._image_paths)):
            img_path = self._image_paths[i]

            img_name = os.path.basename(img_path)
            img_dir = img_path[:img_path.find(img_name) - 1]

            txt_fname = os.path.join(output_dir, img_dir, img_name.replace('jpg', 'txt'))

            res_dir = os.path.join(output_dir, img_dir)
            if not os.path.isdir(res_dir):
                os.makedirs(res_dir)

            with open(txt_fname, 'w') as f:
                f.write(img_path + '\n')
                f.write(str(len(all_boxes[1][i])) + '\n')
                for det in all_boxes[1][i]:
                    f.write('%d %d %d %d %g \n' % (
                        int(det[0]), int(det[1]), int(det[2]) - int(det[0]), int(det[3]) - int(det[1]),
                        det[4]))
        print('Done!')

    def evaluate_detections(self, all_boxes, output_dir='./output/',method_name='SSH'):
        detections_txt_path = os.path.join(output_dir,'detections')
        self.write_detections(all_boxes,detections_txt_path)

        print('Evaluating detections using official WIDER toolbox...')
        path = os.path.join(os.path.dirname(__file__),
                                '..',  'wider_eval_tools')
        eval_output_path = os.path.join(output_dir,'wider_plots')
        if not os.path.isdir(eval_output_path):
            os.mkdir(eval_output_path)
        cmd = 'cd {} && '.format(path)
        cmd += 'matlab -nodisplay -nodesktop '
        cmd += '-r "dbstop if error; '
        cmd += 'wider_eval(\'{:s}\',\'{:s}\',\'{:s}\'); quit;"' \
            .format(detections_txt_path, method_name,eval_output_path)
        print('Running:\n{}'.format(cmd))
        subprocess.call(cmd, shell=True)

