from os.path import join
import numpy as np
import math
from sts import utils
from tqdm import tqdm

from distances import Distance


def pad_sent_pair(s1: list, s2: list) -> tuple:
    if len(s1) == len(s2):
        return s1, s2
    elif len(s1) > len(s2):
        d = len(s2)
        for i in range(d, len(s1)):
            s2.append('null')
    else:
        d = len(s1)
        for i in range(d, len(s2)):
            s1.append('null')
    return s1, s2


def pad_sent_triplet(s1: list, s2: list, s3: list) -> tuple:
    len1, len2, len3 = len(s1), len(s2), len(s3)
    maxlen = max(len1, len2, len3)
    if maxlen == len1:
        _, s2 = pad_sent_pair(s1, s2)
        _, s3 = pad_sent_pair(s1, s3)
    elif maxlen == len2:
        _, s1 = pad_sent_pair(s2, s1)
        _, s3 = pad_sent_pair(s2, s3)
    else:
        _, s1 = pad_sent_pair(s3, s1)
        _, s2 = pad_sent_pair(s3, s2)
    return s1, s2, s3


def remove_pairs_with_score(a: list, b: list, sim: list, targets: list):
    print(f"[Removing Scores: {targets}]")
    anew, bnew, simnew = [], [], []
    for i in range(len(a)):
        if math.floor(sim[i]) not in targets:
            anew.append(a[i])
            bnew.append(b[i])
            simnew.append(sim[i])
    return anew, bnew, simnew


class SemEvalAugmentationStrategy:

    def nclass(self):
        return None

    def augment(self, train_sents_a: list, train_sents_b: list, train_scores: list) -> np.ndarray:
        raise NotImplementedError


class ScoreFormatter:

    def format(self, scores):
        raise NotImplementedError


class ProbabilitiesScoreFormatter(ScoreFormatter):

    def format(self, scores):
        labels = []
        for s in scores:
            ceil = int(math.ceil(s))
            floor = int(math.floor(s))
            tmp = [0, 0, 0, 0, 0, 0]
            if floor != ceil:
                tmp[ceil] = s - floor
                tmp[floor] = ceil - s
            else:
                tmp[floor] = 1
            labels.append(tmp)
        return labels


class BinaryScoreFormatter(ScoreFormatter):

    def __init__(self, threshold: float):
        self.threshold = threshold

    def format(self, scores):
        binary = [0 if s >= self.threshold else 1 for s in scores]
        neg = sum(binary)
        pos = len(binary) - neg
        print(f"Positive Train Pairs: {pos}")
        print(f"Negative Train Pairs: {neg}")
        return binary


class PairBinaryScoreFormatter(ScoreFormatter):

    def __init__(self, threshold: float):
        self.threshold = threshold

    def format(self, scores):
        return [(0, s) if s >= self.threshold else (1, s) for s in scores]


class NoAugmentation(SemEvalAugmentationStrategy):

    def __init__(self, allow_redundancy: bool = False, remove_scores: list = None, formatter: ScoreFormatter = None):
        self.allow_redundancy = allow_redundancy
        self.remove_scores = remove_scores if remove_scores is not None else []
        self.formatter = formatter

    def augment(self, train_sents_a: list, train_sents_b: list, train_scores: list) -> np.ndarray:
        atrain, btrain, simtrain = remove_pairs_with_score(train_sents_a, train_sents_b,
                                                           train_scores, self.remove_scores)
        print(f"Total Train Pairs: {len(atrain)}")
        if self.allow_redundancy:
            train_data = zip(atrain, btrain, simtrain)
            sim = simtrain
        else:
            train_data = list(set(zip(atrain, btrain, simtrain)))
            sim = [y for _, _, y in train_data]
            print(f"Unique Train Pairs: {len(train_data)}")

        print(f"Unique Train Sentences: {len(set(atrain + btrain))}")

        a, b = [], []
        for s1, s2, _ in train_data:
            s1pad, s2pad = pad_sent_pair(s1.split(' '), s2.split(' '))
            a.append(s1pad)
            b.append(s2pad)
        pairs = zip(a, b)

        sim = self.formatter.format(sim) if self.formatter is not None else sim
        print(f"Redundancy in the training set: {'YES' if self.allow_redundancy else 'NO'}")
        return np.array(list(zip(pairs, sim)))


class ClusterAugmentation(SemEvalAugmentationStrategy):

    def __init__(self, threshold: float):
        self.threshold = threshold
        self.classes = None

    def _clusterize(self, sents_a, sents_b, scores):
        segment_a = utils.SemEvalSegment(sents_a)
        segment_b = utils.SemEvalSegment(sents_b)
        return segment_a.clusters(segment_b, scores, self.threshold)

    def nclass(self):
        return self.classes

    def augment(self, train_sents_a: list, train_sents_b: list, train_scores: list) -> np.ndarray:
        sents_a, sents_b, scores = utils.unique_pairs(train_sents_a, train_sents_b, train_scores)

        clusters = self._clusterize(sents_a, sents_b, scores)
        self.classes = len(clusters)

        train_sents, train_sents_raw = [], []
        for i, cluster in enumerate(clusters):
            for sent in cluster:
                if sent in train_sents_a or sent in train_sents_b:
                    train_sents.append((sent.split(' '), i))
                    train_sents_raw.append(sent)
        train_sents = np.array(train_sents)

        print(f"Unique sentences used for clustering: {len(set(sents_a + sents_b))}")
        print(f"Total Train Sentences: {len(set(train_sents_a + train_sents_b))}")
        print(f"Train Sentences Kept: {len(set(train_sents_raw))}")
        print(f"N Clusters: {self.classes}")
        print(f"Max Cluster Size: {max([len(cluster) for cluster in clusters])}")
        print(f"Mean Cluster Size: {np.mean([len(cluster) for cluster in clusters])}")

        return train_sents


class PairAugmentation(SemEvalAugmentationStrategy):

    def __init__(self, threshold):
        # Threshold can be a pair (low, high) or a float, which is the same as (value, value)
        self.threshold = threshold

    def _pairs(self, sents_a, sents_b, scores, threshold):
        segment_a = utils.SemEvalSegment(sents_a)
        segment_b = utils.SemEvalSegment(sents_b)
        pos, neg = utils.pairs(segment_a, segment_b, scores, threshold)
        data = [((s1, s2), 0) for s1, s2 in pos] + [((s1, s2), 1) for s1, s2 in neg]
        return np.array([((s1.split(' '), s2.split(' ')), y) for (s1, s2), y in data])

    def augment(self, train_sents_a: list, train_sents_b: list, train_scores: list) -> np.ndarray:
        train_sents = self._pairs(train_sents_a, train_sents_b, train_scores, self.threshold)
        print(f"Original Train Pairs: {len(train_sents_a)}")
        print(f"Original Unique Train Pairs: {len(set(zip(train_sents_a, train_sents_b)))}")
        print(f"Total Train Pairs: {len(train_sents)}")
        print(f"+ Train Pairs: {len([y for _, y in train_sents if y == 0])}")
        print(f"- Train Pairs: {len([y for _, y in train_sents if y == 1])}")
        return train_sents


class SNLINoNeutralAugmentation(SemEvalAugmentationStrategy):

    def __init__(self, label2int: dict):
        self.label2int = label2int

    def _remove_neutrals(self, asents, bsents, labels):
        id_neutral = self.label2int['neutral']
        a = [sent for i, sent in enumerate(asents) if labels[i] != id_neutral]
        b = [sent for i, sent in enumerate(bsents) if labels[i] != id_neutral]
        sim = [1 if s == self.label2int['contradiction'] else 0 for s in labels if s != id_neutral]
        return a, b, sim

    def nclass(self):
        return 2

    def augment(self, train_sents_a: list, train_sents_b: list, train_labels: list) -> np.ndarray:
        atrain, btrain, simtrain = self._remove_neutrals(train_sents_a, train_sents_b, train_labels)
        print(f"Train Pairs (no neutrals): {len(atrain)}")
        print(f"Unique Train Sentences (no neutrals): {len(set(atrain + btrain))}")
        print(f"+ Train Pairs: {sum([1 for y in simtrain if y == 0])}")
        print(f"- Train Pairs: {sum([1 for y in simtrain if y == 1])}")
        a, b = [], []
        for s1, s2 in zip(atrain, btrain):
            s1pad, s2pad = pad_sent_pair(s1.split(' '), s2.split(' '))
            a.append(s1pad)
            b.append(s2pad)
        return np.array(list(zip(zip(a, b), simtrain)))


class OfflineTripletSampling:

    def sample(self, triplets: list):
        raise NotImplementedError


class SemiHardOfflineTripletSampling(OfflineTripletSampling):

    def __init__(self, model, distance: Distance, m: float, deviation: float):
        self.model = model
        self.distance = distance
        self.m = m
        self.deviation = deviation

    def sample(self, triplets: list):
        result = []
        for a, p, n in triplets:
            emb_a, emb_n = self.model(a), self.model(n)
            dist = self.distance.dist(emb_a, emb_n)
            if self.m >= dist[0] or self.deviation >= dist[0] - self.m:
                result.append((a, p, n))
        return result


class KeepAllOfflineTripletSampling(OfflineTripletSampling):

    def sample(self, triplets: list):
        return triplets


class TripletGenerator:

    def __init__(self, desc: str, is_positive, dump_dir: str = None):
        self.desc = desc
        self.is_positive = is_positive
        self.dump_dir = dump_dir

    def is_negative(self, similarity):
        return not self.is_positive(similarity)

    def anchor_related(self, anchor, train_data, is_annotation_valid):
        pos = []
        for sent1, sent2, annotation in train_data:
            is_sent1 = sent1 == anchor
            is_sent2 = sent2 == anchor
            if (is_sent1 or is_sent2) and is_annotation_valid(annotation):
                pos.append(sent1 if is_sent2 else sent2)
        return pos

    def split_and_pad(self, anchors, positives, negatives):
        a, p, n = [], [], []
        for s1, s2, s3 in zip(anchors, positives, negatives):
            s1pad, s2pad, s3pad = pad_sent_triplet(s1.split(' '), s2.split(' '), s3.split(' '))
            a.append(s1pad)
            p.append(s2pad)
            n.append(s3pad)
        return zip(a, p, n)

    def generate(self, atrain, btrain, simtrain):
        unique_train_data = list(set(zip(atrain, btrain, simtrain)))
        unique_sents = list(set(atrain + btrain))
        anchors, positives, negatives = [], [], []
        for anchor in tqdm(unique_sents, total=len(unique_sents), desc=self.desc):
            for positive in self.anchor_related(anchor, unique_train_data, self.is_positive):
                for negative in self.anchor_related(anchor, unique_train_data, self.is_negative):
                    anchors.append(anchor)
                    positives.append(positive)
                    negatives.append(negative)

        if self.dump_dir is not None:
            with open(join(self.dump_dir, 'anchors'), 'w') as anchor_file, \
                    open(join(self.dump_dir, 'positives'), 'w') as pos_file, \
                    open(join(self.dump_dir, 'negatives'), 'w') as neg_file:
                for anchor in anchors:
                    anchor_file.write(anchor + '\n')
                for pos in positives:
                    pos_file.write(pos + '\n')
                for neg in negatives:
                    neg_file.write(neg + '\n')

        sentences_kept = len(list(set(anchors + negatives + positives)))
        triplets = self.split_and_pad(anchors, positives, negatives)
        unused_y = np.zeros(len(anchors))
        print(f"Triplets: {len(anchors)}")
        print(f"Unique Train Sentences kept: {sentences_kept}")
        return np.array(list(zip(triplets, unused_y)))


class SNLITripletNoAugmentation(SemEvalAugmentationStrategy):

    def __init__(self, label2int: dict, dump_dir: str = None):
        self.dump_dir = dump_dir
        self.base = SNLINoNeutralAugmentation(label2int)
        self.triplet_generator = TripletGenerator(desc='Generating SNLI triplets',
                                                  is_positive=lambda s: s == 0,
                                                  dump_dir=dump_dir)

    def augment(self, train_sents_a: list, train_sents_b: list, train_labels: list) -> np.ndarray:
        # Remove neutrals and get pairs formatted for contrastive loss (0 = positive, 1 = negative)
        train_data = self.base.augment(train_sents_a, train_sents_b, train_labels)
        atrain = [' '.join(row[0][0]) for row in train_data]
        btrain = [' '.join(row[0][1]) for row in train_data]
        simtrain = [row[1] for row in train_data]
        return self.triplet_generator.generate(atrain, btrain, simtrain)


class TripletPairAugmentation(SemEvalAugmentationStrategy):

    def __init__(self, threshold: float, remove_scores: list = None):
        self.threshold = threshold
        self.remove_scores = remove_scores if remove_scores is not None else []
        # Only used for splitting and padding sentences inside the triplets
        self.triplet_generator = TripletGenerator('', None)

    def _triplets(self, sents_a, sents_b, scores):
        segment_a = utils.SemEvalSegment(sents_a)
        segment_b = utils.SemEvalSegment(sents_b)
        unique_sents = set(sents_a + sents_b)
        pos, neg = utils.pairs(segment_a, segment_b, scores, self.threshold)
        anchors, positives, negatives = utils.triplets(unique_sents, pos, neg)
        return list(pos), list(neg), anchors, positives, negatives

    def augment(self, train_sents_a: list, train_sents_b: list, train_scores: list):
        atrain, btrain, simtrain = remove_pairs_with_score(train_sents_a, train_sents_b,
                                                           train_scores, self.remove_scores)
        pos, neg, anchors, positives, negatives = self._triplets(atrain, btrain, simtrain)
        dups = []
        for i in range(len(pos)):
            for j in range(len(neg)):
                if pos[i] == neg[j]:
                    dups.append(pos[i])
        unique_pairs = list(set(pos + neg))
        print(f"Pairs which are positive and negative at the same time: {len(dups)}")
        print(f"Unique Train Pairs: {len(unique_pairs)}")
        print(f"Triplets: {len(anchors)}")
        triplets = self.triplet_generator.split_and_pad(anchors, positives, negatives)
        unused_y = np.zeros(len(anchors))
        return np.array(list(zip(triplets, unused_y)))


class TripletNoAugmentation(SemEvalAugmentationStrategy):

    def __init__(self, threshold: float, remove_scores: list = None):
        self.threshold = threshold
        self.remove_scores = remove_scores if remove_scores is not None else []
        self.triplet_generator = TripletGenerator(desc=f"Generating triplets with threshold={self.threshold}",
                                                  is_positive=lambda s: s >= self.threshold)

    def augment(self, train_sents_a: list, train_sents_b: list, train_scores: list) -> np.ndarray:
        atrain, btrain, simtrain = remove_pairs_with_score(train_sents_a, train_sents_b,
                                                           train_scores, self.remove_scores)
        return self.triplet_generator.generate(atrain, btrain, simtrain)


class SemEvalAugmentationStrategyFactory:

    def __init__(self, loss: str, threshold=3, allow_redundancy: bool = False,
                 augment: bool = False, remove_scores: list = None):
        self.loss = loss
        self.threshold = threshold
        self.allow_redundancy = allow_redundancy
        self.augment = augment
        self.remove_scores = remove_scores if remove_scores is not None else []

    def new(self):
        if self.loss == 'kldiv':
            return NoAugmentation(self.allow_redundancy, self.remove_scores, ProbabilitiesScoreFormatter())
        elif self.loss == 'contrastive':
            if self.augment:
                return PairAugmentation(self.threshold)
            else:
                return NoAugmentation(self.allow_redundancy, self.remove_scores, BinaryScoreFormatter(self.threshold))
        elif self.loss == 'triplet':
            if self.augment:
                return TripletPairAugmentation(self.threshold, self.remove_scores)
            else:
                return TripletNoAugmentation(self.threshold, self.remove_scores)
        else:
            # Softmax based loss
            return ClusterAugmentation(self.threshold)


class SNLIAugmentationStrategyFactory:

    def __init__(self, loss: str, label2int: dict, triplet_dump_dir: str = None):
        self.loss = loss
        self.label2int = label2int
        self.triplet_dump_dir = triplet_dump_dir

    def new(self):
        if self.loss == 'contrastive':
            return SNLINoNeutralAugmentation(self.label2int)
        elif self.loss == 'triplet':
            return SNLITripletNoAugmentation(self.label2int, self.triplet_dump_dir)
        else:
            raise ValueError('Loss must be one of: contrastive/triplet')
