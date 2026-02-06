"""LSTM Encoder-Decoder for vessel trajectory prediction."""

import torch
import torch.nn as nn


class TrajectoryLSTM(nn.Module):
    """Seq2Seq LSTM for predicting future vessel positions.

    Encoder processes input sequence of vessel observations,
    decoder autoregressively generates future predictions.

    Input features (10): delta_x, delta_y, sog, cog_sin, cog_cos,
                         heading_sin, heading_cos, acceleration, rate_of_turn, delta_t
    Output features (4): delta_x, delta_y, sog, cog (sin/cos encoded in loss)
    """

    def __init__(
        self,
        input_dim: int = 10,
        output_dim: int = 4,
        hidden_dim: int = 128,
        num_layers: int = 2,
        dropout: float = 0.2,
        pred_len: int = 20,
    ):
        super().__init__()
        self.pred_len = pred_len
        self.output_dim = output_dim

        self.encoder = nn.LSTM(
            input_dim, hidden_dim, num_layers,
            batch_first=True, dropout=dropout if num_layers > 1 else 0.0,
        )
        self.decoder = nn.LSTM(
            output_dim, hidden_dim, num_layers,
            batch_first=True, dropout=dropout if num_layers > 1 else 0.0,
        )
        self.fc_out = nn.Linear(hidden_dim, output_dim)

    def forward(self, x: torch.Tensor, teacher_forcing_ratio: float = 0.0,
                target: torch.Tensor | None = None) -> torch.Tensor:
        """Forward pass.

        Args:
            x: Input sequence, shape (batch, seq_len, input_dim)
            teacher_forcing_ratio: Probability of using ground truth as decoder input
            target: Ground truth output sequence for teacher forcing,
                    shape (batch, pred_len, output_dim)

        Returns:
            Predicted sequence, shape (batch, pred_len, output_dim)
        """
        batch_size = x.size(0)

        # Encode
        _, (h, c) = self.encoder(x)

        # First decoder input: last known output features from input sequence
        # Use delta_x, delta_y, sog, cog (first 4 features of input)
        decoder_input = x[:, -1:, :self.output_dim]

        outputs = []
        for t in range(self.pred_len):
            out, (h, c) = self.decoder(decoder_input, (h, c))
            pred = self.fc_out(out)  # (batch, 1, output_dim)
            outputs.append(pred)

            # Teacher forcing: use ground truth or own prediction
            if target is not None and torch.rand(1).item() < teacher_forcing_ratio:
                decoder_input = target[:, t:t + 1, :]
            else:
                decoder_input = pred

        return torch.cat(outputs, dim=1)  # (batch, pred_len, output_dim)
