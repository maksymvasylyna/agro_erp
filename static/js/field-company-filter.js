/* Keep related directory selections consistent without hardcoding company names. */
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-erp-cluster-for]").forEach((clusterSelect) => {
    const companySelect = document.getElementById(clusterSelect.dataset.erpClusterFor);
    if (!companySelect) return;

    function applyCluster() {
      const selectedCluster = clusterSelect.value;
      let selectedAllowed = false;
      Array.from(companySelect.options).forEach((option) => {
        if (option.value === "__None" || option.value === "") return;
        const allowed = Boolean(selectedCluster) && selectedCluster !== "__None"
          && option.dataset.clusterId === selectedCluster;
        option.hidden = !allowed;
        option.disabled = !allowed;
        if (option.selected && allowed) selectedAllowed = true;
      });
      if (!selectedAllowed) companySelect.value = "__None";
    }
    applyCluster();
    clusterSelect.addEventListener("change", applyCluster);
  });
});
