import os
import librosa
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import xml.etree.ElementTree as ET


from ast import literal_eval
from typing import List
from glob import glob

from data.data_processing import DataProcessing
from data.onset_detection import OnsetDetect

from constant import (
    PATTERN_DIR,
    PER_DRUM_DIR,
    SAMPLE_RATE,
    ONSET_DURATION,
    PATTERN2CODE,
    ONEHOT_DRUM2CODE,
    MFCC,
    STFT,
    CODE2DRUM,
    METHOD_CLASSIFY,
    METHOD_DETECT,
    METHOD_RHYTHM,
    ROOT_PATH,
    CSV,
    PKL,
    DDM_OWN,
    IDMT,
)

"""
데이터에서 feature를 추출하고, 라벨링하고, 저장하는 클래스
"""


class FeatureExtractor:
    def __init__(
        self,
        data_root_path,
        method_type,
        feature_type,
        feature_param: dict,
        feature_extension=PKL,
    ):
        self.data_root_path = data_root_path
        self.method_type = method_type
        self.feature_type = feature_type
        self.sample_rate = SAMPLE_RATE
        self.feature_param = feature_param
        self.feature_extension = feature_extension
        self.save_path = (
            f"{data_root_path}/{method_type}/{feature_type}.{feature_extension}"
        )
        self.onset_detection = OnsetDetect(SAMPLE_RATE)
        self.data_processing = DataProcessing(data_root_path=ROOT_PATH)

    """
    -- feature 추출한 파일 불러오기
    """

    def load_feature_file(self):
        data_feature_label = None
        if os.path.exists(self.save_path):  # 추출된 feature 존재 한다면
            print("-- ! 기존 feature loading : ", self.save_path)

            if self.feature_extension == CSV:
                data_feature_label = pd.read_csv(
                    self.save_path,
                    index_col=0,
                    converters={"feature": literal_eval, "label": literal_eval},
                )
            elif self.feature_extension == PKL:
                data_feature_label = pd.read_pickle(self.save_path)

            print(
                "-- ! 로딩 완료 ! --",
                "data shape:",
                data_feature_label.shape,
            )
            print("-- ! features ! -- ")
            print(data_feature_label)

        return data_feature_label

    """
    -- feature file 모두 불러오기
    """

    def load_feature_file_all(self):
        feature_file_list = glob(f"{self.data_root_path}/**/*.*", recursive=True)
        print("-- ! feature file all load: ", feature_file_list)
        return feature_file_list

    """
    -- feature 파일 저장하기
    """

    def save_feature_file(self, features: pd.DataFrame):
        if self.feature_extension == CSV:
            # Save csv file
            features.to_csv(self.save_path, sep=",")
        elif self.feature_extension == PKL:
            # Save pickle file
            features.to_pickle(self.save_path)

        print("-- ! 완료 & 새로 저장 ! --")
        print("-- ! location: ", self.save_path)
        print("-- ! features shape:", features.shape)

    """
    -- mfcc feature 추출
    """

    def audio_to_mfcc(self, audio: np.ndarray) -> np.ndarray:
        mfccs = librosa.feature.mfcc(
            y=audio, sr=self.sample_rate, n_mfcc=self.feature_param["n_features"]
        )
        pad_width = self.feature_param["n_times"] - mfccs.shape[1]
        if pad_width > 0:
            mfccs = np.pad(mfccs, pad_width=((0, 0), (0, pad_width)), mode="constant")
        return mfccs

    """
    -- stft feature 추출
    """

    def audio_to_stft(self, audio: np.ndarray) -> np.ndarray:
        # translate STFT
        stft = librosa.stft(
            y=audio,
            n_fft=self.feature_param["n_fft"],
            hop_length=self.feature_param["hop_length"],
            win_length=self.feature_param["win_length"],
            window="hann",
        )
        stft = np.abs(stft, dtype=np.float64)
        if stft.shape[1] < self.feature_param["n_times"]:
            stft_new = np.pad(
                stft,
                pad_width=((0, 0), (0, self.feature_param["n_times"] - stft.shape[1])),
                mode="constant",
            )
        else:
            stft_new = stft[:, : self.feature_param["n_times"]]

        return stft_new

    """
    -- feature type에 따라 feature 추출
    """

    def audio_to_feature(self, audio: np.ndarray) -> np.ndarray:
        result = None
        if self.feature_type == MFCC:
            result = self.audio_to_mfcc(audio)
        elif self.feature_type == STFT:
            result = self.audio_to_stft(audio)

        if self.method_type == METHOD_DETECT:  # separate & detect방식이라면 transpose
            result = np.transpose(result)  # row: time, col: feature

        print(
            "-- length:",
            audio.shape[0] / float(self.sample_rate),
            "secs, ",
            f"{self.feature_type}:",
            result.shape,
        )
        return result

    """
    -- 우리 데이터 기준 classify type (trimmed data) 라벨링
    """

    def get_label_classify_data(self, idx: int, path: str) -> List[int]:
        file_name = os.path.basename(path)  # extract file name
        if PATTERN_DIR in path:  # -- pattern
            pattern_name = file_name[:2]  # -- P1
            label = PATTERN2CODE[pattern_name][idx]
        elif PER_DRUM_DIR in path:  # -- per drum
            drum_name = file_name[:2]  # -- CC
            label = ONEHOT_DRUM2CODE[drum_name]
        return label

    """
    -- 우리 데이터 기준 detect type (sequence data) 라벨링 
        onset position : 1
        onset position with ONSET_DURATION : 0.5
        extra : 0
    """

    def get_audio_position(self, time) -> int:
        return (int)(time * self.sample_rate / self.feature_param["hop_length"])

    def get_label_detect_data(self, audio: np.ndarray, path: str) -> List[List[int]]:
        file_name = os.path.basename(path)
        onsets_arr = self.onset_detection.onset_detection(audio)
        last_time = (
            self.feature_param["n_times"]
            * self.feature_param["hop_length"]
            / self.sample_rate
        )

        labels = [[0.0] * len(CODE2DRUM) for _ in range(self.feature_param["n_times"])]
        pattern_idx = 0
        for onset in onsets_arr:
            if onset >= last_time:
                break

            soft_start_position = self.get_audio_position(
                max((onset - ONSET_DURATION), 0)
            )
            onset_position = self.get_audio_position(onset)
            soft_end_position = self.get_audio_position(
                min(onset + ONSET_DURATION, last_time)
            )

            if any(drum in file_name for _, drum in CODE2DRUM.items()):  # per drum
                one_hot_label: List[int] = ONEHOT_DRUM2CODE[file_name[:2]]
            else:  # pattern
                pattern_name = file_name[:2]  # -- P1
                one_hot_label: List[int] = PATTERN2CODE[pattern_name][pattern_idx]
                pattern_idx += 1
            for i in range(soft_start_position, soft_end_position):
                if (np.array(labels[i]) == np.array(one_hot_label)).all():
                    continue
                labels[i] = (np.array(one_hot_label) / 2).tolist()
            labels[(int)(onset_position)] = one_hot_label

        return labels

    """
    -- XML file 읽기
    """

    def load_xml_file(self, file_path):
        try:
            # XML 파일을 파싱합니다.
            tree = ET.parse(file_path)
            # 루트 엘리먼트를 얻습니다.
            root = tree.getroot()
            return root
        except ET.ParseError as e:
            print(f"XML 파일을 파싱하는 동안 오류가 발생했습니다: {e}")
            return None

    """
    -- XML file에서 onset 읽어오기
    """

    def get_onsets_arr_from_xml(self, xml_path: str):
        print("-- ! xml file location: ", xml_path)

        onset_sec_list = []
        xml_root = self.load_xml_file(xml_path)
        # transcription 엘리먼트의 정보 출력
        transcription_element = xml_root.find(".//transcription")
        events = transcription_element.findall("event")
        for event in events:
            onset_sec = event.find("onsetSec").text
            onset_sec_list.append(float(onset_sec))

        print("-- ! 파싱한 onsets: ", onset_sec_list)
        return onset_sec_list

    """
    -- onset 라벨링 
    """

    def get_label_rhythm_data(self, last_time, onsets_arr: List[float]) -> List[float]:
        labels = [0.0] * self.feature_param["n_times"]

        for onset in onsets_arr:
            if self.get_audio_position(onset) >= self.feature_param["n_times"]:
                break

            soft_start_position = self.get_audio_position(
                max((onset - ONSET_DURATION), 0)
            )
            onset_position = self.get_audio_position(onset)
            soft_end_position = self.get_audio_position(
                min(onset + ONSET_DURATION, last_time)
            )

            for i in range(soft_start_position, soft_end_position):
                if i >= self.feature_param["n_times"]:
                    break

                if labels[i] == 1.0:
                    continue

                labels[i] = 0.5
            labels[(int)(onset_position)] = 1.0

        return labels

    """
    -- classify type feature, label 추출
    """

    def classify_feature_extractor(self, audio_paths: List[str]) -> pd.DataFrame:
        data_feature_label = []

        print(f"-- ! ADT type : {self.method_type} ! --")
        print(f"-- ! {self.feature_type} feature extracting ! --")
        for path in audio_paths:
            print("-- curret file: ", path)
            # -- librosa feature load
            audio, _ = librosa.load(path, sr=self.sample_rate, res_type="kaiser_fast")

            if DDM_OWN in path:  # 우리 데이터라면
                # -- trimmed audio
                trimmed_audios = self.data_processing.trim_audio_per_onset(audio)
                # -- trimmed feature
                for idx, taudio in enumerate(trimmed_audios):
                    trimmed_feature = self.audio_to_feature(taudio)
                    # -- label: 드럼 종류
                    label = self.get_label_classify_data(idx, path)
                    data_feature_label.append([trimmed_feature.tolist(), label])

        feature_df = pd.DataFrame(data_feature_label, columns=["feature", "label"])
        return feature_df

    """
    -- detect type feature, label 추출
    """

    def detect_feature_extractor(self, audio_paths: List[str]) -> pd.DataFrame:
        data_feature_label = []

        print(f"-- ! ADT type : {self.method_type} ! --")
        print(f"-- ! {self.feature_type} feature extracting ! --")
        for path in audio_paths:
            print("-- curret file: ", path)
            # -- librosa feature load
            audio, _ = librosa.load(path, sr=self.sample_rate, res_type="kaiser_fast")

            if DDM_OWN in path:  # 우리 데이터라면
                # -- trim first onset
                audio = self.data_processing.trim_audio_first_onset(audio)
                # -- feature extract
                feature = self.audio_to_feature(audio)
                # -- label: 드럼 종류마다 onset 여부
                label = self.get_label_detect_data(audio, path)
                data_feature_label.append([feature.tolist(), label])

        feature_df = pd.DataFrame(data_feature_label, columns=["feature", "label"])
        return feature_df

    """
    -- detect type label 그래프
    """

    def show_detect_label_plot(self, label):
        label = np.array(label)
        for i in range(len(CODE2DRUM)):
            plt.subplot(8, 1, i + 1)
            plt.plot(label[:, i])
        plt.title("Model label")
        plt.show()

    """
    -- rhythm type feature, label 추출
    """

    def rhythm_feature_extractor(self, audio_paths: List[str]):
        data_feature_label = []

        print(f"-- ! ADT type : {self.method_type} ! --")
        print(f"-- ! {self.feature_type} feature extracting ! --")
        for path in audio_paths:
            print("-- curret file: ", path)
            # -- librosa feature load
            audio, _ = librosa.load(path, sr=self.sample_rate, res_type="kaiser_fast")

            # if DDM_OWN in path:  # 우리 데이터라면
            #     # -- trim first onset
            #     audio = self.data_processing.trim_audio_first_onset(audio)
            #     # -- feature extract
            #     feature = self.audio_to_feature(audio)
            #     # -- label: onset 여부
            #     onsets_arr = self.onset_detection.onset_detection(audio)
            #     label = self.get_label_rhythm_data(
            #         len(audio) / self.sample_rate, onsets_arr
            #     )
            #     data_feature_label.append([feature.tolist(), label])

            if IDMT in path:  # IDMT data
                if "MIX" not in path:
                    continue

                # -- feature extract
                feature = self.audio_to_feature(audio)
                # -- label: onset 여부
                file_name = os.path.basename(path)[:-4]  # 파일 이름
                file_paths = path.split("/")[:-2]  # 뒤에서 2개 제외한 폴더 list

                xml_file = os.path.join(os.path.join(*file_paths), "annotation_xml")
                xml_file = os.path.join(xml_file, f"{file_name}.xml")
                onsets_arr = self.get_onsets_arr_from_xml(xml_file)
                label = self.get_label_rhythm_data(
                    len(audio) / self.sample_rate, onsets_arr
                )
                data_feature_label.append([feature.tolist(), label])

        feature_df = pd.DataFrame(data_feature_label, columns=["feature", "label"])
        if len(feature_df) > 0:
            self.show_rhythm_label_plot(feature_df.label[0])
        return feature_df

    """
    -- rhythm type label 그래프
    """

    def show_rhythm_label_plot(self, label):
        label = np.array(label)
        plt.plot(label)
        plt.title("Model label")
        plt.show()

    """ 
    -- method type 에 따라 feature, label 추출 후 저장
    """

    def feature_extractor(self, audio_paths: List[str]):
        features_df_origin = self.load_feature_file()  # load feature file

        features_df_new = None
        if self.method_type == METHOD_CLASSIFY:
            features_df_new = self.classify_feature_extractor(audio_paths)
        elif self.method_type == METHOD_DETECT:
            features_df_new = self.detect_feature_extractor(audio_paths)
        elif self.method_type == METHOD_RHYTHM:
            features_df_new = self.rhythm_feature_extractor(audio_paths)

        # Convert into a Panda dataframe & Add dataframe
        features_total_df = features_df_new
        if features_df_origin is not None:
            features_total_df = pd.concat([features_df_origin, features_df_new])

        # Save feature file
        self.save_feature_file(features_total_df)