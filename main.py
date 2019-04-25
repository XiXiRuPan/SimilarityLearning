import torch
from torchvision import datasets, transforms
from  torch.utils.data import DataLoader
from models import ContrastiveNet, ArcNet
from trainers import ContrastiveTrainer, ArcTrainer
from datasets import ContrastiveDataset

# Config
use_cuda = torch.cuda.is_available() and True
device = torch.device('cuda' if use_cuda else 'cpu')
mnist_path = '/localHD/MNIST' if use_cuda else '../MNIST'

# Load Dataset
transform = transforms.Compose([
    transforms.ToTensor(),
    transforms.Normalize((0.1307,), (0.3081,))])
trainset = datasets.MNIST(mnist_path, download=True, train=True, transform=transform)
testset = datasets.MNIST(mnist_path, download=True, train=False, transform=transform)


def contrastive():
    # Prepare Dataset
    # TODO shuffle and recombine train and test before each epoch
    # TODO return visualization loader too
    print("Recombining Dataset...")
    xtrain = trainset.data.unsqueeze(1).type(torch.FloatTensor)
    ytrain = trainset.targets
    xtest = testset.data.unsqueeze(1).type(torch.FloatTensor)
    ytest = testset.targets
    dataset = ContrastiveDataset(xtrain, ytrain)
    test_dataset = ContrastiveDataset(xtest, ytest)
    loader = DataLoader(dataset, batch_size=128, shuffle=True, num_workers=4)
    test_loader = DataLoader(test_dataset, batch_size=128, shuffle=False, num_workers=4)
    # Training
    trainer = ContrastiveTrainer(ContrastiveNet(), device, margin=2.0, distance='euclidean')
    #trainer = ContrastiveTrainer(ContrastiveNet(), device, margin=0.3, distance='cosine')
    return trainer, loader, test_loader


def arc():
    # TODO return visualization loader too
    trainer = ArcTrainer(ArcNet(), device, nfeat=2, nclass=10, margin=0.3)
    loader = DataLoader(trainset, batch_size=128, shuffle=True, num_workers=4)
    test_loader = DataLoader(testset, batch_size=128, shuffle=False, num_workers=4)
    return trainer, loader, test_loader


trainer, train_loader, test_loader = arc()

visu_loader = DataLoader(testset, batch_size=128, shuffle=False, num_workers=4)
trainer.visualize(visu_loader, "test-before-train-arc")

for epoch in range(20):
    trainer.train(epoch+1, train_loader, test_loader, visu_loader)

trainer.visualize(visu_loader, "test-20-epochs-arc-m=3,5-s=4")

