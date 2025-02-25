import math
import os
import librosa
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
import tensorflow as tf
import matplotlib.pyplot as plt
from glob import glob
from datetime import datetime
from tensorflow.keras.callbacks import EarlyStopping
from sklearn.metrics import (
    multilabel_confusion_matrix,
    classification_report,
    ConfusionMatrixDisplay,
)

from data.data_processing import DataProcessing
from feature.feature_extractor import FeatureExtractor
from constant import (
    DETECT_CODE2DRUM,
    DRUM2CODE,
    DRUM_TYPES_3,
    LABEL_COLUMN,
    LABEL_DDM,
    LABEL_TYPE,
    SAMPLE_RATE,
    PKL,
    METHOD_CLASSIFY,
    METHOD_DETECT,
    METHOD_RHYTHM,
    FEATURE_PARAM,
    ROOT_PATH,
    RAW_PATH,
    CODE2DRUM,
    TEST,
    TRAIN,
    VALIDATION,
    IMAGE_PATH,
)


class BaseModel:
    def __init__(
        self,
        training_epochs,
        opt_learning_rate,
        batch_size,
        method_type,
        feature_type,
        feature_extension=PKL,
        compile_mode=True,
        class_dict=CODE2DRUM,
    ):
        self.model = None
        self.training_epochs = training_epochs
        self.opt_learning_rate = opt_learning_rate
        self.batch_size = batch_size
        self.method_type = method_type
        self.feature_type = feature_type
        self.feature_extension = feature_extension
        self.compile_mode = compile_mode
        self.class_dict = class_dict
        self.feature_param = FEATURE_PARAM[method_type][feature_type]
        self.sample_rate = SAMPLE_RATE
        self.x_train: np.ndarray = None
        self.y_train: np.ndarray = None
        self.x_val: np.ndarray = None
        self.y_val: np.ndarray = None
        self.x_test: np.ndarray = None
        self.y_test: np.ndarray = None
        self.save_folder_path = f"../models/{method_type}"
        self.save_path = f"{self.save_folder_path}/{method_type}_{feature_type}"
        self.model_save_type = "h5"

    def save(self):
        """
        -- 학습한 모델 저장하기
        """
        # 현재 날짜와 시간 가져오기
        date_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        # 폴더 생성
        os.makedirs(self.save_folder_path, exist_ok=True)
        # 모델 저장
        model_path = f"{self.save_path}_{date_time}.{self.model_save_type}"
        self.model.save(model_path)
        print("--! save model: ", model_path)

    def load_model(self, model_file=None):
        """
        -- method_type과 feature type에 맞는 가장 최근 모델 불러오기
        """
        model_files = glob(f"{self.save_path}_*.{self.model_save_type}")
        if model_files is None or len(model_files) == 0:
            print("-- ! No pre-trained model ! --")
            return

        model_files.sort(reverse=True)  # 최신 순으로 정렬
        load_model_file = model_files[0]  # 가장 최근 모델

        if model_file is not None:  # 불러오고자 하는 특정 모델 파일이 있다면
            load_model_file = model_file

        print("-- ! load model: ", load_model_file)
        self.model = tf.keras.models.load_model(
            load_model_file, compile=self.compile_mode
        )

    @staticmethod
    def grouping_label(y_data, group_dict):
        """
        -- label을 grouping하는 함수
        -- y_data: 원래 label data
        -- group_dict: 라벨링을 그룹핑한 객체
        -- ex) {
                 "OH": ["CC", "OH", "CH"],
                 "SD": ["TT", "SD",],
                 "KK": ["KK",]
               }
        """
        new_y = np.zeros((y_data.shape[0], len(group_dict)))

        for l_idx, l_arr in enumerate(y_data):
            temp_label = np.zeros(len(group_dict))
            for idx, (_, labels) in enumerate(group_dict.items()):
                # 우선순위: 1 > 0.5 > 0
                label_value = max(l_arr[DRUM2CODE[l]] for l in labels)
                temp_label[idx] = label_value if not math.isnan(label_value) else 0
            new_y[l_idx] = temp_label

        del y_data
        # np.set_printoptions(threshold=np.inf, linewidth=np.inf)  # inf = infinity
        # print("-- ! 그룹핑 후 라벨 ! --\n", new_y)
        return new_y

    @staticmethod
    def _get_x_y(
        method_type: str,
        feature_df: pd.DataFrame,
        label_type: str = LABEL_DDM,
    ):
        if method_type == METHOD_CLASSIFY:
            X = np.array(feature_df.feature.tolist())
            y = feature_df[[drum for _, drum in CODE2DRUM.items()]].to_numpy()

            del feature_df
            return X, y
        if method_type in METHOD_DETECT:
            # Y: HH-LABEL_REF..., ST, SD, KK-LABEL_DDM | X: mel-1, mel-2, mel-3, ...

            X = feature_df.drop(LABEL_COLUMN, axis=1).to_numpy()
            y = feature_df[LABEL_TYPE[label_type]["column"]].to_numpy()

            del feature_df
            return X, y
        if method_type in METHOD_RHYTHM:
            # label(onset 여부) | mel-1, mel-2, mel-3, ...
            X = feature_df.drop(["label"], axis=1).to_numpy()
            y = feature_df["label"].to_numpy()

            del feature_df
            return X, y

    # 데이터 분할을 위한 함수 정의
    @staticmethod
    def split_data(data, chunk_size):
        num_samples, num_features = data.shape
        num_chunks = num_samples // chunk_size

        # 나머지 부분을 제외한 데이터만 사용
        data = data[: num_chunks * chunk_size, :]

        # reshape을 통해 3D 배열로 변환
        return data.reshape((num_chunks, chunk_size, num_features))
        # 데이터 분할을 위한 함수 정의

    @staticmethod
    def split_x_data(data, chunk_size):
        num_samples, num_features = data.shape
        num_chunks = num_samples // chunk_size

        # 나머지 부분을 제외한 데이터만 사용
        data = data[: num_chunks * chunk_size, :]

        # reshape을 통해 3D 배열로 변환
        return data.reshape((num_chunks, chunk_size, num_features, 1))

    @staticmethod
    def split_x_y_data(X, y, chunk_size):
        num_samples, num_features = y.shape
        num_chunks = num_samples // chunk_size

        # 나머지 부분을 제외한 데이터만 사용
        new_y = y[: num_chunks * chunk_size, :]

        num_samples_x, num_features_x = X.shape
        num_chunks_x = num_samples_x // chunk_size

        # 나머지 부분을 제외한 데이터만 사용
        new_X = X[: num_chunks_x * chunk_size, :]

        # reshape을 통해 3D 배열로 변환
        new_y = new_y.reshape((num_chunks, chunk_size, num_features))
        new_X = new_X.reshape((num_chunks_x, chunk_size, num_features_x, 1))

        # 라벨 값이 모두 0인 데이터 인덱스 구하기
        zero_indices = np.where(np.all(new_y == 0, axis=(1, 2)))[0]
        new_y = np.delete(new_y, zero_indices, axis=0)
        new_X = np.delete(new_X, zero_indices, axis=0)

        return new_X, new_y

    @staticmethod
    def transform_peakpick_from_dict(data_dict, delta):
        """
        peak picking from dict data
        input : float32 array
        """
        result_dict = {}
        for key, values in data_dict.items():
            item_value = np.array(values)
            peak_value = np.zeros(len(item_value))

            # peak_pick를 통해 몇 번째 인덱스가 peak인지 추출
            peaks = librosa.util.peak_pick(
                item_value,
                pre_max=0,
                post_max=3,
                pre_avg=0,
                post_avg=3,
                delta=delta,
                wait=4,
            )
            for idx in peaks:
                peak_value[idx] = 1
            result_dict[key] = peak_value
        return result_dict

    # tranform 2D array to dict
    @staticmethod
    def transform_arr_to_dict(arr_data):
        result_dict = {}
        for code, drum in DETECT_CODE2DRUM.items():
            result_dict[drum] = [row[code] for row in arr_data]
        return result_dict

    # tranform dict to 2D array (detect)
    @staticmethod
    def transform_dict_to_arr(dict_data):
        """
        {'OH': [0., 0., 0., ..., 0., 0., 0.], 'TT': [0., 0., 0., ..., 0., 0., 0.], 'SD': [0., 0., 0., ..., 0., 0., 0.], 'KK': [0., 0., 0., ..., 0., 0., 0.]}
        =>
        [[0,0,0,0],
        [0,0,0,0],
        ...
        [0,0,0,0]]
        """
        result_arr = np.stack([dict_data[key] for key in dict_data.keys()], axis=1)
        return result_arr

    @staticmethod
    def show_f1score_delta_plot(delta_values, f1_scores):
        plt.plot(delta_values, f1_scores)
        plt.title("F1-Score vs. Delta Values")
        plt.xlabel("Delta")
        plt.ylabel("F1-Score")
        date_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        plt.savefig(f"{IMAGE_PATH}/f1score-delta-{date_time}.png")
        plt.show()

    @staticmethod
    def get_confusion_matrix(y_true, y_pred):
        return multilabel_confusion_matrix(y_true, y_pred)

    @staticmethod
    def print_confusion_matrix(cm, y_test_data, y_pred):
        # confusion matrix & precision & recall
        print("-- ! confusion matrix ! --")
        print(cm)

        print("-- ! classification report ! --")
        print(classification_report(y_test_data, y_pred, digits=4))

    @staticmethod
    def show_confusion_matrix(cm, labels):
        fig, axs = plt.subplots(
            nrows=1, ncols=len(labels), figsize=(8, 6 * len(labels))
        )

        for i, label in enumerate(labels):
            ax = axs[i]
            ax.imshow(cm[i], interpolation="nearest", cmap=plt.cm.Blues)
            ax.set(
                xticks=np.arange(cm.shape[2]),
                yticks=np.arange(cm.shape[1]),
                xticklabels=["N", "P"],
                yticklabels=["N", "P"],
                title=f"Confusion matrix for label {label}",
                ylabel="True label",
                xlabel="Predicted label",
            )

            # Rotate the tick labels for better readability
            plt.setp(
                ax.get_xticklabels(), rotation=45, ha="right", rotation_mode="anchor"
            )

            # Loop over data dimensions and create text annotations
            fmt = "d"
            thresh = cm[i].max() / 2.0
            for x in range(cm[i].shape[0]):
                for y in range(cm[i].shape[1]):
                    ax.text(
                        y,
                        x,
                        format(cm[i][x, y], fmt),
                        ha="center",
                        va="center",
                        color="white" if cm[i][x, y] > thresh else "black",
                    )

        fig.tight_layout()
        plt.show()

    def create_model_dataset(self, X: np.array, y: np.array, split_type: str):
        # Implement model
        pass

    def create_dataset(
        self,
        split_data: dict[str],
        label_type: str = LABEL_DDM,
        group_dict: str = DRUM_TYPES_3,
    ):
        # -- load train, validation, test
        # split_data_df = FeatureExtractor.load_dataset_from_split_data_file(
        #     self.method_type, self.feature_type, self.feature_extension, split_data
        # )

        for split_type, data_type in split_data.items():
            print("-- !! split type >> ", split_type)
            print("-- !! data types >> ", data_type)

            # dataframe 초기화
            combined_df = FeatureExtractor._init_combine_df(
                self.method_type, self.feature_type
            )
            for dt in data_type:
                # feature 파일을 읽어와 DataFrame으로 변환
                data_feature_label = FeatureExtractor.load_feature_file(
                    self.method_type,
                    self.feature_type,
                    self.feature_extension,
                    dt,
                    split_type,
                )
                # 현재 파일의 데이터를 combined_df에 추가
                combined_df = pd.concat(
                    [combined_df, data_feature_label], ignore_index=True
                )
                del data_feature_label
            # -- get X, y
            X, y = BaseModel._get_x_y(self.method_type, combined_df, label_type)
            del combined_df
            y = BaseModel.grouping_label(y, group_dict)
            # 각 model마다 create dataset
            self.create_model_dataset(X, y, split_type)

            del X
            del y

        self.fill_all_dataset()

        # -- print shape
        self.print_dataset_shape()

    def split_dataset(self, X, y, split_type):
        if split_type == TRAIN:
            self.x_train = X
            self.y_train = y
        elif split_type == VALIDATION:
            self.x_val = X
            self.y_val = y
        elif split_type == TEST:
            self.x_test = X
            self.y_test = y

        del X, y
        return

    def fill_all_dataset(self):
        # test 없으면 train에서
        if self.x_test is None and self.x_train is not None:
            x_train, x_test, y_train, y_test = train_test_split(
                self.x_train,
                self.y_train,
                test_size=0.2,
                random_state=42,
                stratify=self.y_train,
            )
            self.split_dataset(x_train, y_train, TRAIN)
            self.split_dataset(x_test, y_test, TEST)

            del x_train, x_test, y_train, y_test

        # validation 없으면 train에서
        if self.x_val is None and self.x_train is not None:
            x_train, x_val, y_train, y_val = train_test_split(
                self.x_train,
                self.y_train,
                test_size=0.2,
                random_state=42,
                stratify=self.y_train,
            )
            self.split_dataset(x_train, y_train, TRAIN)
            self.split_dataset(x_val, y_val, VALIDATION)

            del x_train, x_val, y_train, y_val

    def print_dataset_shape(self):
        if not self.x_train is None:
            print("x_train : ", self.x_train.shape)
            print("y_train : ", self.y_train.shape)
        if not self.x_val is None:
            print("x_val : ", self.x_val.shape)
            print("y_val : ", self.y_val.shape)
        if not self.x_test is None:
            print("x_test : ", self.x_test.shape)
            print("y_test : ", self.y_test.shape)

    def create(self):
        # Implement model creation logic
        pass

    def train(self):
        # Implement model train logic
        early_stopping = EarlyStopping(
            monitor="val_loss", patience=3, restore_best_weights=True, mode="auto"
        )

        history = self.model.fit(
            self.x_train,
            self.y_train,
            batch_size=self.batch_size,
            validation_data=(self.x_val, self.y_val),
            epochs=self.training_epochs,
            callbacks=[early_stopping],
        )

        stopped_epoch = early_stopping.stopped_epoch
        print("--! finish train : stopped_epoch >> ", stopped_epoch, " !--")

        return history

    def data_2d_reshape(self, data):
        return data.reshape((-1, self.n_classes))

    def evaluate(self):
        # Implement model evaluation logic
        print("\n# Evaluate on test data")

        results = self.model.evaluate(
            self.x_test, self.y_test, batch_size=self.batch_size
        )
        print("test loss:", results[0])
        print("test accuracy:", results[1])

        labels = list(self.class_dict.values())

        try:
            # -- predict
            y_pred = self.model.predict(self.x_test)

            # -- reshape
            y_test_data = self.data_2d_reshape(self.y_test)
            y_pred = self.data_2d_reshape(y_pred)

            if self.method_type == METHOD_DETECT:
                delta_values = np.linspace(0, 1, 11)  # 0부터 1까지 10개의 값
                result = []
                for delta in delta_values:
                    tmp_y_test_data = y_test_data
                    tmp_y_pred = y_pred
                    # -- binary
                    # y array -> y dict -> peakpick dict -> y array
                    tmp_y_test_data = DataProcessing.convert_array_dtype_float32(
                        tmp_y_test_data
                    )
                    tmp_y_test_data = BaseModel.transform_arr_to_dict(tmp_y_test_data)
                    tmp_y_test_data = BaseModel.transform_peakpick_from_dict(
                        tmp_y_test_data, delta
                    )
                    tmp_y_test_data = BaseModel.transform_dict_to_arr(tmp_y_test_data)

                    tmp_y_pred = BaseModel.transform_arr_to_dict(tmp_y_pred)
                    tmp_y_pred = BaseModel.transform_peakpick_from_dict(
                        tmp_y_pred, delta
                    )
                    tmp_y_pred = BaseModel.transform_dict_to_arr(tmp_y_pred)

                    result.append(
                        classification_report(
                            tmp_y_test_data, tmp_y_pred, output_dict=True
                        )["weighted avg"]["f1-score"]
                    )
                    print(f"------------------ delta : {delta} ------------------")
                    cm = BaseModel.get_confusion_matrix(tmp_y_test_data, tmp_y_pred)
                    BaseModel.print_confusion_matrix(cm, tmp_y_test_data, tmp_y_pred)
                    BaseModel.show_confusion_matrix(cm, labels)
                BaseModel.show_f1score_delta_plot(delta_values, result)
            else:
                y_pred = np.where(y_pred > self.predict_standard, 1.0, 0.0)
                cm = BaseModel.get_confusion_matrix(y_test_data, y_pred)
                BaseModel.print_confusion_matrix(cm, y_test_data, y_pred)
                BaseModel.show_confusion_matrix(cm, labels)

        except Exception as e:
            print(e)

    def extract_feature(self, data_path: str = f"{ROOT_PATH}/{RAW_PATH}"):
        """
        모델 학습에 사용하는 피쳐 추출하는 함수
        """
        audio_paths = DataProcessing.get_paths(data_path)
        FeatureExtractor.feature_extractor(
            audio_paths, self.method_type, self.feature_type, self.feature_extension
        )

    def run(self):
        """
        데이터셋 생성, 모델 생성, 학습, 평가, 모델 저장 파이프라인
        """
        self.create_dataset()
        self.create()
        self.train()
        self.evaluate()
        self.save()

    def predict(self, wav_path, bpm, delay):
        # Implement model predict logic
        pass
