# TODO: sheban et repertoire de kub-pysandboxes et flag rigeur. utiliser uvx ?
minikube mount .:/mnt/pysandboxes &
kubectl apply -f kube-pysandboxes.yaml
kubectl delete pod pysandboxes-test

