'''Operators for diversity amend.
'''

from typing import override, Dict
import openai
import os
import pandas as pd
import tiktoken

from ..config import settings
from .operator import Meta, Operator, Field
from ..storage.dataset import DataType
from ..task.task_type import TaskType

class DiversityEnhanceOperator(Operator):
    def __init__(self, **kwargs):
        self.api_key = kwargs.get('api_key',"")
        self.model = kwargs.get('model', "gpt-4o")
        self.score_file = kwargs.get('score_file', "./detailed_scores.csv")

        self.token_encoder = tiktoken.encoding_for_model("gpt-4")  # 使用tiktoken进行token计数

    @classmethod
    @override
    def accept(cls, data_type, task_type) -> bool:
        if data_type == DataType.CODE and task_type == TaskType.AUGMENTATION:
            return True
        return False
    
    @classmethod
    @override
    def get_config(cls) -> list[Field]:
        return [
            Field('api-key', Field.FieldType.STRING, 'OpenAI API key', ""),
            Field('model', Field.FieldType.STRING, 'OpenAI model name', "gpt-4o"),
            Field('score_file', Field.FieldType.STRING, 'Score result file path', "./detailed_scores.csv")
        ]
    

    @classmethod
    @override
    def get_meta(cls) -> Meta:
        return Meta(
            name='DiversityxEnhanceOperator',
            description='Diversity enhance.'
        )
    
    def get_cost(self, dataset) -> Dict:
        cost = {}
        # operator name
        cost["name"] = "DiversityxEnhanceOperator"
        # records count
        cost["ri"] = self.get_type_count(self.score_file) * 4
        # time of one record
        cost["ti"] = 21.5
        # cpi time of one record
        input_token = 494
        cost["intoken"] = input_token
        output_token = 1534
        cost["outtoken"] = output_token
        cost["ci"] = round( (input_token+output_token*4)*0.000018125 , 4)
        # operator type
        cost["type"] = "LLM"
        return cost

    def count_tokens(self, text):
        """使用tiktoken计算文本的token数量"""
        return len(self.token_encoder.encode(text))

    @override
    def execute(self, dataset):
        
        # gpt-4o (github版)
        client = openai.OpenAI(
            api_key = self.api_key,
            # base_url = "https://models.inference.ai.azure.com"
            base_url = settings.GPT_URL
        )

        # files
        df = pd.read_csv(dataset.meta_path, na_values=['nan', 'None', ''])
        code_dir = [dir for dir in dataset.dirs if dir.data_type == DataType.CODE][0]
        type_code = self.get_one_file_per_type(self.score_file)
        print(type_code)

        for index, (type, code_file_name) in enumerate(type_code):
            
            if pd.isna(code_file_name):
                continue
        
            # get code data
            code_file_path = os.path.join(code_dir.data_path,code_file_name)
            with open(code_file_path, 'rb') as f_code:
                code_data = f_code.read().decode('utf-8')


            new_code_datas = self.call_gpt4o(client, code_data)
            # try:
            #     new_code_data = self.call_gpt4o(client, code_data, 60)
            # except Exception as e:
            #     print(f"调用超时")
            #     # 异常时至少保留参数变异结果
            #     continue
            new_code_list = new_code_datas.split("@@@")
            # 一次返回5段代码
            for index, new_code_data in enumerate(new_code_list):
                new_code_file_name = f"d{index}_{code_file_name}"
                new_code_path = os.path.join(code_dir.data_path,new_code_file_name)

                start = new_code_data.find("{")
                end = new_code_data.rfind("}")
                json_text = new_code_data[start:end+1]

                with open(new_code_path, 'wb') as f:
                    f.write(json_text.encode('utf-8'))
                new_data = pd.DataFrame({"image":"", "code": [new_code_file_name], "type": [type]})
                df = pd.concat([df, new_data], ignore_index=True)  # 合并数据
            # 保存新数据
            df.to_csv(dataset.meta_path, index=False)
            print("配置项多样性增强完成")

    @staticmethod
    def get_one_file_per_type(csv_path):
        """
        对 CSV 中每个 type 随机选择一个 file 返回，结果格式为 {type: file}
        """
        df = pd.read_csv(csv_path)

        # 筛选出 syntax_score == 100 的记录
        filtered_df = df[df['syntax_score'] == 100]
        
        if filtered_df.empty:
            return {}  # 如果没有符合条件的记录，返回空字典


        # 按 type 分组后随机选择一条记录
        # result = (
        #     filtered_df.groupby('type')
        #     .apply(lambda x: x.sample(1))
        #     .set_index('code')['type']
        #     .to_dict()
        # )
        result = [
            (type_val, code_val) 
            for type_val, code_val in filtered_df.groupby('type')
            .apply(lambda x: x.sample(1))
            .set_index('type')['code']
            .items()
        ]
        return result
    
    # 获取图表种类数
    @staticmethod
    def get_type_count(score_file):

        df = pd.read_csv(score_file)
        
        # 筛选出 syntax_score == 100 的记录
        filtered_df = df[df['syntax_score'] == 100]
        
        if filtered_df.empty:
            return 0

        field_name = 'type'
        # 统计非空不同值数量
        num_unique = df[field_name].dropna().nunique()

        return num_unique


    def call_gpt4o (self, client, code_data):

        message_content = "以下的echarts配置json代码中的配置项多样性不够，请模仿给出的代码，在保持图表类型的前提下，为其增加合理的配置，给出四个新的可运行的echarts配置json代码，四个代码之间以“@@@”分割。请只输出json代码以及分隔符@@@，不需要描述与分析。"

        response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    # {"role": "system", "content": "你是一个熟悉 ECharts 的前端开发专家"},
                    {"role": "user", "content": message_content},
                    {"role": "user", "content": code_data},
                ],
            )
            
        # 计算输入token
        input_tokens = self.count_tokens(message_content) + self.count_tokens(code_data)
        print(f"输入token数{input_tokens}")

        response_text = response.choices[0].message.content
        
        # 计算输出token
        output_tokens = self.count_tokens(response_text)
        print(f"输出token数{output_tokens}")
        # print("收到的结果为：" + response_text)
        start = response_text.find("{")
        end = response_text.rfind("}")
        json_text = response_text[start:end+1]

        return json_text
