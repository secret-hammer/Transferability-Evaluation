import torch
from tqdm.auto import tqdm
import torch.nn.functional as F

def leep(
    model: torch.nn.Module, 
    data_loader: torch.utils.data.DataLoader, 
    number_of_target_labels: int,
    device: torch.device = 'cuda'
    ) -> float:
    """Calculates LEEP score from https://arxiv.org/abs/2002.12462

    data_loader should return pairs of (images, labels), where labels are classes of
    the images, represented as zero-indexed integer

    :param model: Pytorch multi-class model
    :param data_loader: DataLoader for the downstream dataset
    :param number_of_target_labels: The number of the downstream dataset classes
    :param device: Device to run on
    :returns: LEEP score
    :rtype: float
    """

    # Make sure to calculate LEEP on all of the data
    assert data_loader.drop_last is False
    
    model.to(device).eval()

    with torch.no_grad():
        
        # Actual dataset length can be smaller if it's not divisable by batch_size - this is used for tensors pre-allocation
        predicted_dataset_length = len(data_loader) * data_loader.batch_size

        # Get number of upstream dataset classes
        original_output_shape = model(next(iter(data_loader))[0].to(device=device)).shape[1]
        
        # Allocate empty arrays ahead of time

        # Omega from Eq(1) and Eq(2)
        categorical_probability = torch.zeros((predicted_dataset_length, original_output_shape), dtype=torch.float32, device=device)
        
        all_labels = torch.zeros(predicted_dataset_length, dtype=torch.int64, device=device)

        # Joint porbability from Eq (1)
        p_target_label_and_source_distribution = torch.zeros(number_of_target_labels, original_output_shape, device=device)
        
        soft_max = torch.nn.Softmax(dim=1) 
        
        # This calculates actual dataset length 
        actual_dataset_length = 0

        tqdm_dataloader = tqdm(data_loader)
        for i, (images, labels) in enumerate(tqdm_dataloader):
            current_batch_length = labels.shape[0]
            actual_dataset_length += current_batch_length

            images = images.to(device)
            labels = labels.to(device)
            result = model(images)

            # Change to probability
            result = soft_max(result)
            
            categorical_probability[i*data_loader.batch_size:i*data_loader.batch_size + current_batch_length] = result
            all_labels[i*data_loader.batch_size:i*data_loader.batch_size + current_batch_length] = labels

            p_target_label_and_source_distribution.scatter_add_(0, labels.squeeze().unsqueeze(-1).repeat(1, result.size(-1)), result.squeeze())
            # p_target_label_and_source_distribution[labels] += result.squeeze()
        
        # Shrink tensors to actually fit to the actual dataset length
        categorical_probability = torch.narrow(categorical_probability, dim=0, start=0, length=actual_dataset_length)
        all_labels = torch.narrow(all_labels, dim=0, start=0, length=actual_dataset_length)
        

        p_target_label_and_source_distribution /= actual_dataset_length
        p_marginal_z_distribution = torch.sum(p_target_label_and_source_distribution, axis=0)
        p_empirical_conditional_distribution = torch.div(p_target_label_and_source_distribution, p_marginal_z_distribution)
        
        total_sum = torch.sum(torch.log(torch.sum((p_empirical_conditional_distribution[all_labels] * categorical_probability), axis=1)))
        return (total_sum / actual_dataset_length).item()

# logits means possibiilities
def get_leep_score(logits, target_labels, device):

    if type(logits) != torch.Tensor:
        logits = torch.tensor(logits).to(device)
    logits = F.softmax(logits, dim=1)
    
    unique_labels = torch.unique(target_labels).flatten()
    max_unique_label, _ = torch.max(unique_labels, dim=0)
    joint_distribution = torch.zeros(int(max_unique_label.item())+1, logits.shape[1]).to(device)
    joint_distribution.scatter_add_(0, target_labels.squeeze().unsqueeze(-1).repeat(1, logits.size(-1)), logits.squeeze())

    joint_distribution /= logits.shape[0]
    
    marginal_distribution = torch.sum(joint_distribution, axis=0)
    
    conditional_distribution = torch.div(joint_distribution, marginal_distribution)
    
    total_sum = torch.sum(torch.log(torch.sum(conditional_distribution[target_labels] * logits, axis=1)))
    return float((total_sum / logits.shape[0]).item())
    