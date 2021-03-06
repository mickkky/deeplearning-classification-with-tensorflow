import tensorflow as tf
import resnet
from tf_keras import utils
import os
import math


def main():
    # Training and test data
    data_path = '/path/to/your/data'
    test_ratio = 0.1
    validation = True
    val_ratio = 0.1

    # Hyper-parameters
    # Net structure
    depth = 18               # An int from: 18, 34, 50, 101, 152
    num_classes = 2
    # Training parameters
    optimizer = 'sgd'        # A string from: 'agd', 'adam', 'momentum'
    learning_rate = 1e-4
    momentum = None          # Necessary if optimizer is 'momentum'
    batch_size = 32
    epochs = 500
    epochs_every_test = 100
    epochs_every_save = 100
    early_stop_num = 3
    method = 'restart'       # A string from: 'restart', 'restore'

    #  Log file setting
    trained_model_directory = 'directory/to/your/restored/model' # Necessary if method is "restore"
    model_directory = 'path/to/save/model'
    utils.create_directory(model_directory)
    model_name = 'resnet%d_%s_%s.ckpt' % (depth, optimizer, utils.record_time())
    model_path = os.path.join(model_directory, model_name)
    log_directory = 'directory/to/save/log_files'
    utils.create_directory(log_directory)
    log_filename = 'resnet%d_%s_%s.log' % (depth, optimizer, utils.record_time())
    summarize = True         # True if summarize in tensorboard

    # Load data and preprocess it
    train_list, test_list, val_list = utils.data_split(data_path, test_ratio, validation, val_ratio)
    num_train_sample = utils.cal_num(train_list)
    num_test_sample = utils.cal_num(test_list)
    train_filenames, train_labels = utils.get_filename_label(data_path, train_list)
    test_filenames, test_labels = utils.get_filename_label(data_path, test_list)
    train_dataset = tf.data.Dataset.from_tensor_slices((train_filenames, train_labels)).map(
        lambda x, y: utils._parse_function(x, y, num_classes)).shuffle(
        buffer_size=1024, reshuffle_each_iteration=True).batch(batch_size)
    test_dataset = tf.data.Dataset.from_tensor_slices((test_filenames, test_labels)).map(
        lambda x, y: utils._parse_function(x, y, num_classes)).batch(batch_size).repeat(1)
    iterator = tf.data.Iterator.from_structure(train_dataset.output_types, train_dataset.output_shapes)
    example_batch, label_batch = iterator.get_next()
    train_init_op = iterator.make_initializer(train_dataset)
    test_init_op = iterator.make_initializer(test_dataset)
    # validation
    if validation:
        num_val_sample = utils.cal_num(val_list)
        val_filenames, val_labels = utils.get_filename_label(data_path, val_list)
        val_dataset = tf.data.Dataset.from_tensor_slices((val_filenames, val_labels)).map(
            lambda x, y: utils._parse_function(x, y, num_classes)).batch(batch_size).repeat(1)
        val_init_op = iterator.make_initializer(val_dataset)
    else:
        pass

    # Define input x and output y
    x = tf.placeholder('float', shape=[None, 224, 224, 3], name='x')
    y_ = tf.placeholder('float', shape=[None, num_classes], name='y')
    net = resnet.Resnet(depth, num_classes)
    net.model(x)
    train_op, correct_count, loss, accuracy = utils.train(net.logits, net.prob, y_, optimizer, learning_rate, momentum)

    # Summarize in tensorboard
    if summarize:
        tf.summary.scalar('loss', loss)
        tf.summary.scalar('accuracy', accuracy)
        summary_op = tf.summary.merge_all()

    saver = tf.train.Saver()

    with tf.Session(config=tf.ConfigProto(allow_soft_placement=True, log_device_placement=True)) as sess:
        # logs writer
        if summarize:
            writer = tf.summary.FileWriter(log_directory, sess.graph)
        fo = open(os.path.join(log_directory, log_filename), 'w')

        if method == 'restart':
            init_op = tf.global_variables_initializer()
            sess.run(init_op)
        elif method == 'restore':
            saver.restore(sess, tf.train.latest_checkpoint(trained_model_directory))
            print("Model restored...", file=fo)
        else:
            raise ValueError("Invalid METHOD parameter, please input 'restart' or 'restore'.")

        print('%d training images and %d test images' % (num_train_sample, num_test_sample), file=fo)
        step = 0
        m = math.ceil(num_train_sample / batch_size)
        train_accuracies = []
        train_losses = []
        val_accuracies = []
        val_losses = []
        for i in range(epochs):
            sess.run(train_init_op)
            train_acc_ = 0.0
            train_loss_ = 0.0
            try:
                while True:
                    batch_X, batch_Y = sess.run([example_batch, label_batch])
                    if summarize:
                        _, acc_, loss_, summary= sess.run([train_op, accuracy, loss, summary_op],
                                                             feed_dict={x: batch_X, y_: batch_Y})
                        writer.add_summary(summary)
                    else:
                        _, acc_, loss_ = sess.run([train_op, accuracy, loss],
                                                  feed_dict={x: batch_X, y_: batch_Y})
                    train_acc_ += acc_
                    train_loss_ += loss_
                    step += 1
            except tf.errors.OutOfRangeError:
                train_accuracy = train_acc_ / m
                train_loss = train_loss_ / m
                print("%s: epoch %d, train_accuracy = %f, train_loss = %f."
                      % (utils.print_time(), i, train_accuracy, train_loss), file=fo)
            train_accuracies.append(train_accuracy)
            train_losses.append(train_loss)
            # validation
            if validation:
                sess.run(val_init_op)
                total_correct_count = 0
                val_loss_ = 0.0
                try:
                    while True:
                        X_val, Y_val = sess.run([example_batch, label_batch])
                        true_count, current_loss = sess.run([correct_count, loss], feed_dict={x: X_val, y_: Y_val})
                        total_correct_count += true_count
                        val_loss_ += current_loss
                except tf.errors.OutOfRangeError:
                    val_accuracy = total_correct_count / num_val_sample
                    val_loss = val_loss_ / m
                    print("%s:          val_accuracy = %f, val_loss = %f" % (
                    utils.print_time(), val_accuracy, val_loss), file=fo)
                val_accuracies.append(val_accuracy)
                val_losses.append(val_loss)
                # early stop
                if utils.early_stop(train_accuracies, train_losses, val_accuracies, val_losses, n=early_stop_num):
                    break
                else:
                    pass
            else:
                # ealry stop
                if utils.early_stop(train_accuracies, train_losses, n=early_stop_num):
                    break
                else:
                    pass
            # test
            if (i + 1) % epochs_every_test == 0:
                sess.run(test_init_op)
                total_correct_count = 0
                test_loss_ = 0.0
                try:
                    while True:
                        X_test, Y_test = sess.run([example_batch, label_batch])
                        true_count, current_loss = sess.run([correct_count, loss], feed_dict={x: X_test, y_: Y_test})
                        total_correct_count += true_count
                        test_loss_ += current_loss
                except tf.errors.OutOfRangeError:
                    test_accuracy = total_correct_count / num_test_sample
                    test_loss = test_loss_ / m
                    print("%s: epoch %d, test_accuracy = %f, test_loss = %f" % (
                    utils.print_time(), i, test_accuracy, test_loss), file=fo)
            if (i + 1) % epochs_every_save == 0:
                saver.save(sess, model_path, global_step=step)
        print("Done training -- epoch limited reached")
        # test
        sess.run(test_init_op)
        total_correct_count = 0
        test_loss_ = 0.0
        try:
            while True:
                X_test, Y_test = sess.run([example_batch, label_batch])
                true_count, current_loss = sess.run([correct_count, loss], feed_dict={x: X_test, y_: Y_test})
                total_correct_count += true_count
                test_loss_ += current_loss
        except tf.errors.OutOfRangeError:
            print("Done test！", file=fo)
            test_accuracy = total_correct_count / num_test_sample
            test_loss = test_loss_ / m
            print("Test_accuracy = %f, test_loss = %f" % (test_accuracy, test_loss), file=fo)

        fo.close()
        saver.save(sess, model_path, global_step=step)


if __name__ == '__main__':
    main()