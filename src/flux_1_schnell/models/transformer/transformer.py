import mlx.core as mx
from mlx import nn

from flux_1_schnell.config.config import Config
from flux_1_schnell.models.transformer.ada_layer_norm_continous import AdaLayerNormContinuous
from flux_1_schnell.models.transformer.embed_nd import EmbedND
from flux_1_schnell.models.transformer.joint_transformer_block import JointTransformerBlock
from flux_1_schnell.models.transformer.single_transformer_block import SingleTransformerBlock
from flux_1_schnell.models.transformer.time_text_embed import TimeTextEmbed


class Transformer(nn.Module):

    def __init__(self, weights: dict):
        super().__init__()
        self.pos_embed = EmbedND()
        self.x_embedder = nn.Linear(64, 3072)
        self.time_text_embed = TimeTextEmbed()
        self.context_embedder = nn.Linear(4096, 3072)
        self.transformer_blocks = [JointTransformerBlock(i) for i in range(19)]
        self.single_transformer_blocks = [SingleTransformerBlock(i) for i in range(38)]
        self.norm_out = AdaLayerNormContinuous(3072, 3072)
        self.proj_out = nn.Linear(3072, 64)

        # Load the weights after all components are initialized
        self.update(weights)

    def predict(
            self,
            t: int,
            prompt_embeds: mx.array,
            pooled_prompt_embeds: mx.array,
            hidden_states: mx.array,
            config: Config
    ) -> mx.array:
        time_step = config.time_steps[t]
        time_step = mx.broadcast_to(time_step, (1,))
        hidden_states = self.x_embedder(hidden_states)
        text_embeddings = self.time_text_embed.forward(time_step, pooled_prompt_embeds)
        encoder_hidden_states = self.context_embedder(prompt_embeds)
        txt_ids = Transformer._prepare_text_ids()
        img_ids = Transformer._prepare_latent_image_ids()
        ids = mx.concatenate((txt_ids, img_ids), axis=1)
        image_rotary_emb = self.pos_embed.forward(ids)

        for block in self.transformer_blocks:
            encoder_hidden_states, hidden_states = block.forward(
                hidden_states=hidden_states,
                encoder_hidden_states=encoder_hidden_states,
                text_embeddings=text_embeddings,
                rotary_embeddings=image_rotary_emb
            )

        hidden_states = mx.concatenate([encoder_hidden_states, hidden_states], axis=1)

        for block in self.single_transformer_blocks:
            hidden_states = block.forward(
                hidden_states=hidden_states,
                text_embeddings=text_embeddings,
                rotary_embeddings=image_rotary_emb
            )

        hidden_states = hidden_states[:, encoder_hidden_states.shape[1]:, ...]
        hidden_states = self.norm_out.forward(hidden_states, text_embeddings)
        hidden_states = self.proj_out(hidden_states)
        noise = hidden_states
        return noise

    @staticmethod
    def _prepare_latent_image_ids() -> mx.array:
        latent_image_ids = mx.zeros((64, 64, 3))
        latent_image_ids = latent_image_ids.at[:, :, 1].add(mx.arange(0, 64)[:, None])
        latent_image_ids = latent_image_ids.at[:, :, 2].add(mx.arange(0, 64)[None, :])
        latent_image_ids = mx.repeat(latent_image_ids[None, :], 1, axis=0)
        latent_image_ids = mx.reshape(latent_image_ids, (1, 4096, 3))
        return latent_image_ids

    @staticmethod
    def _prepare_text_ids() -> mx.array:
        return mx.zeros((1, 256, 3))
