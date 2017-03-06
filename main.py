#import math
from __future__ import print_function
import requests
import os

def download(url, filename):
    """ utility function to download a file """
    response = requests.get(url, stream=True)
    with open(filename, "wb") as handle:
        for data in response.iter_content():
            handle.write(data)

#locations = ['Tutorials/SLUHandsOn', 'Examples/LanguageUnderstanding/ATIS/BrainScript']

##### СМЕНИТЕ ЭТИ ЛОКАЦИИ НА РАСПОЛОЖЕНИЕ ФАЙЛОВ У ВАС
locations = ['C:/Users/Dima/cntk/Examples/Text/ATIS', 'C:/Users/Dima/cntk/Examples/Text/ATIS/Data']
data = {
  'train': { 'file': 'atis.trainf.ctf', 'location': 0 },
  'test': { 'file': 'atis.testf.ctf', 'location': 0 },
  'query': { 'file': 'query1.wl', 'location': 1 },
  'slots': { 'file': 'slots1.wl', 'location': 1 }
}

for item in data.values():
    location = locations[item['location']]
    path = os.path.join('..', location, item['file'])
    if os.path.exists(path):
        print("Reusing locally cached:", item['file'])
        # Update path
        item['file'] = path
    elif os.path.exists(item['file']):
        print("Reusing locally cached:", item['file'])
    else:
        print("Starting download:", item['file'])
        url = "https://github.com/Microsoft/CNTK/blob/v2.0.beta8.0/%s/%s?raw=true"%(location, item['file'])
        download(url, item['file'])
        print("Download completed")


import numpy as np
from cntk.blocks import default_options, LSTM, Placeholder, Input        # building blocks
from cntk.layers import Embedding, Recurrence, Dense, BatchNormalization # layers
from cntk.models import Sequential                                       # higher level things
from cntk.utils import ProgressPrinter, log_number_of_parameters
from cntk.io import MinibatchSource, CTFDeserializer
from cntk.io import StreamDef, StreamDefs, INFINITELY_REPEAT, FULL_DATA_SWEEP
from cntk import *
from cntk.learner import adam_sgd, learning_rate_schedule

#vocab_size = 685 ; num_labels = 68 ; #num_intents = 26
vocab_size = 1295 ; num_labels = 85 ; #num_intents = 26


# model dimensions
input_dim  = vocab_size
label_dim  = num_labels
emb_dim    = 150
hidden_dim = 300

def create_model():
    with default_options(initial_state=0.1):
        return Sequential([
            Embedding(emb_dim),
            Recurrence(LSTM(hidden_dim), go_backwards=False),
            Dense(num_labels)
        ])

# peek
model = create_model()
print(len(model.layers))
print(model.layers[0].E.shape)
print(model.layers[2].b.value)


def create_reader(path, is_training):
    return MinibatchSource(CTFDeserializer(path, StreamDefs(
         query         = StreamDef(field='S0', shape=vocab_size,  is_sparse=True),
         #intent_unused = StreamDef(field='S1', shape=num_intents, is_sparse=True),
         slot_labels   = StreamDef(field='S1', shape=num_labels,  is_sparse=True)
     )), randomize=is_training, epoch_size = INFINITELY_REPEAT if is_training else FULL_DATA_SWEEP)


# peek
reader = create_reader(data['train']['file'], is_training=True)
reader.streams.keys()

def create_criterion_function(model):
    labels = Placeholder(name='labels')
    ce   = cross_entropy_with_softmax(model, labels)
    errs = classification_error(model, labels)
    return combine ([ce, errs]) # (features, labels) -> (loss, metric)

def train(reader, model, max_epochs=16):
    # criterion: (model args, labels) -> (loss, metric)
    #   here  (query, slot_labels) -> (ce, errs)
    criterion = create_criterion_function(model)

    criterion.replace_placeholders({criterion.placeholders[0]: Input(vocab_size),
                                    criterion.placeholders[1]: Input(num_labels)})

    # training config
    #epoch_size = 18000  # 18000 samples is half the dataset size
    epoch_size = 18000
    minibatch_size = 70

    # LR schedule over epochs
    # In CNTK, an epoch is how often we get out of the minibatch loop to
    # do other stuff (e.g. checkpointing, adjust learning rate, etc.)
    # (we don't run this many epochs, but if we did, these are good values)
    lr_per_sample = [0.003] * 4 + [0.0015] * 24 + [0.0003]
    lr_per_minibatch = [x * minibatch_size for x in lr_per_sample]
    lr_schedule = learning_rate_schedule(lr_per_minibatch, UnitType.minibatch, epoch_size)

    # Momentum
    momentum_as_time_constant = momentum_as_time_constant_schedule(700)

    # We use a variant of the Adam optimizer which is known to work well on this dataset
    # Feel free to try other optimizers from
    # https://www.cntk.ai/pythondocs/cntk.learner.html#module-cntk.learner
    learner = adam_sgd(criterion.parameters,
                       lr=lr_schedule, momentum=momentum_as_time_constant,
                       low_memory=True,
                       gradient_clipping_threshold_per_sample=15, gradient_clipping_with_truncation=True)

    # trainer
    trainer = Trainer(model, criterion.outputs[0], criterion.outputs[1], learner)

    # process minibatches and perform model training
    log_number_of_parameters(model)
    progress_printer = ProgressPrinter(tag='Training')
    # progress_printer = ProgressPrinter(freq=100, first=10, tag='Training') # more detailed logging

    t = 0
    for epoch in range(max_epochs):  # loop over epochs
        epoch_end = (epoch + 1) * epoch_size
        while t < epoch_end:  # loop over minibatches on the epoch
            data = reader.next_minibatch(minibatch_size, input_map={  # fetch minibatch
                criterion.arguments[0]: reader.streams.query,
                criterion.arguments[1]: reader.streams.slot_labels
            })
            trainer.train_minibatch(data)  # update model with it
            t += data[criterion.arguments[1]].num_samples  # samples so far
            progress_printer.update_with_trainer(trainer, with_metric=True)  # log progress
        loss, metric, actual_samples = progress_printer.epoch_summary(with_metric=True)

    return loss, metric

def do_train():
    global model
    model = create_model()
    reader = create_reader(data['train']['file'], is_training=True)
    train(reader, model)
    
do_train()

def evaluate(reader, model):
    criterion = create_criterion_function(model)
    criterion.replace_placeholders({criterion.placeholders[0]: Input(num_labels)})

    # process minibatches and perform evaluation
    lr_schedule = learning_rate_schedule(1, UnitType.minibatch)
    momentum_as_time_constant = momentum_as_time_constant_schedule(0)
    dummy_learner = adam_sgd(criterion.parameters, 
                             lr=lr_schedule, momentum=momentum_as_time_constant, low_memory=True)
    evaluator = Trainer(model, criterion.outputs[0], criterion.outputs[1], dummy_learner)
    progress_printer = ProgressPrinter(tag='Evaluation')

    while True:
        minibatch_size = 500
        data = reader.next_minibatch(minibatch_size, input_map={  # fetch minibatch
            criterion.arguments[0]: reader.streams.query,
            criterion.arguments[1]: reader.streams.slot_labels
        })
        if not data:                                 # until we hit the end
            break
        metric = evaluator.test_minibatch(data)
        progress_printer.update(0, data[criterion.arguments[1]].num_samples, metric) # log progress
    loss, metric, actual_samples = progress_printer.epoch_summary(with_metric=True)

    return loss, metric
    
    
def do_test():
    reader = create_reader(data['test']['file'], is_training=False)
    evaluate(reader, model)
    
do_test()
print(model.layers[2].b.value)

# load dictionaries
query_wl = [line.rstrip('\n') for line in open(data['query']['file'], encoding='UTF-8')]
slots_wl = [line.rstrip('\n') for line in open(data['slots']['file'])]
query_dict = {query_wl[i]:i for i in range(len(query_wl))}
slots_dict = {slots_wl[i]:i for i in range(len(slots_wl))}

print(query_dict)


if __name__ == "__main__":
    while True:
        try:
            seq=input('Enter:')
            # let's run a sequence through
            #seq = 'BOS траты от социальной в курской 2016 EOS'
            mass=seq.split(' ');
            print(seq.split(' '))
            #kw=[]
            #for w in seq.split(' '):
            #    kw.append(query_dict[w])
            w = [query_dict[w] for w in seq.split(' ')] # convert to word indices
            print(w)
            onehot = np.zeros([len(w),len(query_dict)+1], np.float32)
            for t in range(len(w)):
                onehot[t,w[t]] = 1
        
            print(onehot)
    
            pred = model.eval({model.arguments[0]:[onehot]})
            print(pred.shape)
            best = np.argmax(pred,axis=2)
            print(best[0])
            print(list(zip(seq.split(),[slots_wl[s] for s in best[0]])))

        except KeyError:
            print("Something went wrong")
            #print(e1)
            
        